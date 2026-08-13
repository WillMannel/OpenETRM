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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline response headers a browser-facing API should always send -- see
    ARCHITECTURE.md's "Production operability, DR, and security review". None of
    these are a substitute for the frontend's own CSP/CORS posture; they're the
    floor every response gets regardless of which route served it.

    `Strict-Transport-Security` is deliberately conditional on the request having
    actually arrived over HTTPS (`request.url.scheme == "https"`) -- sending HSTS
    on a plain-HTTP local/dev request would be a lie (the browser would remember a
    promise this server isn't keeping), and behind a TLS-terminating reverse proxy
    the proxy is usually the one adding it anyway. Real deployments should still
    confirm their proxy sets it if this app is never reached directly over HTTPS."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
