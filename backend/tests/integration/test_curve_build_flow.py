import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from tests.conftest import AuthHeadersFactory


@pytest.mark.asyncio
async def test_seed_quotes_and_build_curve(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER)
    quotes = [
        {"quote_date": "2026-01-15", "delivery_month": "2026-06-01", "price": 3.10},
        {"quote_date": "2026-01-15", "delivery_month": "2026-07-01", "price": 3.25},
        {"quote_date": "2026-01-15", "delivery_month": "2026-08-01", "price": 3.05},
    ]
    for quote in quotes:
        resp = await client.post("/api/v1/market-data/quotes", json=quote, headers=trader_headers)
        assert resp.status_code == 201

    build_resp = await client.post(
        "/api/v1/curves/build", json={"as_of_date": "2026-01-15"}, headers=trader_headers
    )
    assert build_resp.status_code == 201
    curve = build_resp.json()
    assert curve["status"] == "PUBLISHED"
    assert [p["tenor_bucket"] for p in curve["points"]] == ["2026-06", "2026-07", "2026-08"]
    assert curve["points"][0]["price"] == pytest.approx(3.10)

    viewer_headers = await auth_headers(UserRole.VIEWER)
    get_resp = await client.get(f"/api/v1/curves/{curve['id']}", headers=viewer_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == curve["id"]


@pytest.mark.asyncio
async def test_build_curve_with_no_quotes_returns_422(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER)
    resp = await client.post(
        "/api/v1/curves/build", json={"as_of_date": "2026-01-15"}, headers=trader_headers
    )
    assert resp.status_code == 422
