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


def _route_template(request: Request) -> str:
    """The matched route's path template (e.g. /api/v1/trades/{trade_id}) once FastAPI
    has resolved routing, so metrics collapse per-id paths into one series instead of
    one per id. Falls back to the raw path if routing never resolved (a 404, or an
    exception raised before/during route matching)."""
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    return request.url.path


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                duration = time.perf_counter() - start
                http_requests_total.labels(request.method, _route_template(request), "500").inc()
                http_request_duration_seconds.labels(
                    request.method, _route_template(request)
                ).observe(duration)
                logger.exception("request failed: %s %s", request.method, request.url.path)
                raise
        finally:
            request_id_ctx.reset(token)

        duration = time.perf_counter() - start
        route_template = _route_template(request)
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
