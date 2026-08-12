import logging

import redis.asyncio as redis_asyncio
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.metrics import render_metrics
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version="0.1.0")
# Middleware order matters: Starlette applies them outermost-last-added, so
# CORSMiddleware (added last) wraps everything else, and gets first look at a
# preflight OPTIONS request before it ever reaches RequestContextMiddleware/routing.
app.add_middleware(RequestContextMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness: the process is up and serving requests. Deliberately checks nothing
    external -- a slow/down dependency should surface on /health/ready, not make the
    orchestrator think the process itself needs restarting."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def readiness(response: Response) -> dict[str, object]:
    """Readiness: can this instance actually serve traffic right now? Pings Postgres
    and Redis; either being unreachable flips the response to 503 without raising, so
    the body always reports which dependency failed.

    Deliberately does *not* reuse the app's shared engine (app.core.db.engine) or Arq
    pool (app.core.jobs.get_arq_pool) -- both cache a connection pool at module scope
    for the process's one long-lived event loop, which is right for request handling
    but wrong for a probe: a short-lived throwaway connection here means a real
    network problem is always caught fresh, and it avoids ever handing a pooled
    connection from *this* check to a future request on a different event loop (bit
    us for real under pytest-asyncio's per-test-function event loops, where the shared
    engine was getting reused across tests each on their own loop)."""
    checks: dict[str, str] = {}
    healthy = True

    probe_engine = create_async_engine(settings.database_url)
    try:
        async with probe_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        healthy = False
        checks["database"] = f"error: {exc}"
        logger.warning("readiness check: database unreachable: %s", exc)
    finally:
        await probe_engine.dispose()

    redis_client = redis_asyncio.from_url(settings.redis_url)
    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        healthy = False
        checks["redis"] = f"error: {exc}"
        logger.warning("readiness check: redis unreachable: %s", exc)
    finally:
        await redis_client.aclose()

    if not healthy:
        response.status_code = 503
    return {"status": "ok" if healthy else "unavailable", "checks": checks}


@app.get("/metrics", tags=["observability"])
async def metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)
