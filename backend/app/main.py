import logging

from fastapi import FastAPI, Response
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.db import engine
from app.core.jobs import get_arq_pool
from app.core.logging import configure_logging
from app.core.metrics import render_metrics
from app.core.middleware import RequestContextMiddleware

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(RequestContextMiddleware)
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
    the body always reports which dependency failed."""
    checks: dict[str, str] = {}
    healthy = True

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        healthy = False
        checks["database"] = f"error: {exc}"
        logger.warning("readiness check: database unreachable: %s", exc)

    try:
        pool = await get_arq_pool()
        await pool.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        healthy = False
        checks["redis"] = f"error: {exc}"
        logger.warning("readiness check: redis unreachable: %s", exc)

    if not healthy:
        response.status_code = 503
    return {"status": "ok" if healthy else "unavailable", "checks": checks}


@app.get("/metrics", tags=["observability"])
async def metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)
