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
