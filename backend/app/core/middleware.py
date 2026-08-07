"""Per-request cross-cutting concerns: a correlation id (generated or propagated from
an inbound X-Request-ID header) and Prometheus request metrics. Kept as one middleware
rather than two so there's a single place that measures wall-clock time around
call_next.
"""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_ctx
from app.core.metrics import http_request_duration_seconds, http_requests_total

logger = logging.getLogger("app.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        token = request_id_ctx.set(request_id)
        route_template = request.url.path
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - start
            http_requests_total.labels(request.method, route_template, "500").inc()
            http_request_duration_seconds.labels(request.method, route_template).observe(duration)
            logger.exception("request failed: %s %s", request.method, request.url.path)
            raise
        finally:
            request_id_ctx.reset(token)

        duration = time.perf_counter() - start
        # Prefer the matched route's path template (set by FastAPI once routing
        # resolves) so e.g. /api/v1/trades/<uuid> and /api/v1/trades/<uuid2> collapse
        # into one metrics series instead of one per id.
        route = request.scope.get("route")
        if route is not None and getattr(route, "path", None):
            route_template = route.path
        http_requests_total.labels(request.method, route_template, str(response.status_code)).inc()
        http_request_duration_seconds.labels(request.method, route_template).observe(duration)

        response.headers["X-Request-ID"] = request_id
        logger.info(
            "%s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration * 1000,
        )
        return response
