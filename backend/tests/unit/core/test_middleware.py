from starlette.requests import Request

from app.core.middleware import _route_template


class _FakeRoute:
    def __init__(self, path: str) -> None:
        self.path = path


def _make_request(path: str, route: object | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "server": ("test", 80),
        "client": ("test", 123),
    }
    if route is not None:
        scope["route"] = route
    return Request(scope)


def test_route_template_uses_the_matched_route_path():
    """This is the fix under test: metrics must key off the route *template*, not the
    raw path -- otherwise every distinct UUID in a path creates its own Prometheus
    label series, which is exactly the unbounded-cardinality problem route templating
    exists to avoid (previously only applied on the success path, not on exceptions)."""
    request = _make_request(
        "/api/v1/trades/3fa85f64-5717-4562-b3fc-2c963f66afa6",
        route=_FakeRoute("/api/v1/trades/{trade_id}"),
    )
    assert _route_template(request) == "/api/v1/trades/{trade_id}"


def test_route_template_falls_back_to_the_raw_path_when_routing_never_resolved():
    request = _make_request("/does-not-exist")
    assert _route_template(request) == "/does-not-exist"
