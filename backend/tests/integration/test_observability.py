import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_liveness_always_ok(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_reports_a_check_per_dependency(client: AsyncClient):
    resp = await client.get("/health/ready")
    # No live Postgres/Redis in this test environment (SQLite stands in for the DB, and
    # there's no Redis at all), so this always comes back unavailable here -- what this
    # asserts is the *shape* of the response, not a green result.
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert set(body["checks"]) == {"database", "redis"}


@pytest.mark.asyncio
async def test_readiness_never_leaks_the_raw_exception_to_an_unauthenticated_caller(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """/health/ready is unauthenticated (orchestrators/load balancers probe it with
    no credential) -- a database/Redis connection failure must report only
    "error" in the response body, never the underlying exception's text (hostnames,
    ports, driver error strings), which is exactly the kind of reconnaissance detail
    an anonymous caller shouldn't get handed during a real outage. Forces both
    dependency checks to fail deterministically (rather than relying on this test
    environment happening to have no reachable Postgres/Redis) by making the probe
    connections themselves raise a distinctive message, then asserts that message
    never appears in the response."""
    import app.main as main_module

    secret_looking_detail = "super-secret-internal-hostname-db.internal:5432"

    class _BoomEngine:
        def connect(self) -> object:
            raise RuntimeError(secret_looking_detail)

        async def dispose(self) -> None:
            pass

    class _BoomRedis:
        async def ping(self) -> None:
            raise RuntimeError(secret_looking_detail)

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(main_module, "create_async_engine", lambda *a, **k: _BoomEngine())
    monkeypatch.setattr(main_module.redis_asyncio, "from_url", lambda *a, **k: _BoomRedis())

    resp = await client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["checks"] == {"database": "error", "redis": "error"}
    assert secret_looking_detail not in resp.text


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_text_format(client: AsyncClient):
    # exercise a request first so at least one series has been recorded
    await client.get("/health")

    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "http_requests_total" in resp.text


@pytest.mark.asyncio
async def test_responses_carry_a_request_id_header(client: AsyncClient):
    resp = await client.get("/health")
    assert "X-Request-ID" in resp.headers

    resp2 = await client.get("/health", headers={"X-Request-ID": "test-fixed-id"})
    assert resp2.headers["X-Request-ID"] == "test-fixed-id"
