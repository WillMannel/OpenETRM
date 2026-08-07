"""Prometheus metrics: request count and latency, labeled by method/route-template/
status. Route *template* (e.g. `/api/v1/trades/{trade_id}`), not the raw path, so
metrics cardinality doesn't explode with one series per UUID.
"""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

registry = CollectorRegistry()

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests handled",
    labelnames=("method", "path", "status_code"),
    registry=registry,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    labelnames=("method", "path"),
    registry=registry,
)


def render_metrics() -> tuple[bytes, str]:
    """Returns (body, content_type) ready to hand straight to a Response."""
    return generate_latest(registry), CONTENT_TYPE_LATEST
