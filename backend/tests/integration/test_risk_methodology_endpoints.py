import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.modules.trade_capture.models import Book, Counterparty
from tests.conftest import AuthHeadersFactory


async def _confirmed_book_with_curve(
    client: AsyncClient, db_session: AsyncSession, trader_headers: dict, risk_headers: dict
) -> str:
    counterparty = Counterparty(name="Theta Trading")
    book = Book(name="Theta Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()

    trade_payload = {
        "trade_date": "2026-01-10",
        "counterparty_id": str(counterparty.id),
        "book_id": str(book.id),
        "trade_type": "SWAP",
        "buy_sell": "BUY",
        "volume": 10000,
        "fixed_price": 3.00,
        "delivery_start_month": "2026-06-01",
        "delivery_end_month": "2026-06-01",
    }
    trade_resp = await client.post("/api/v1/trades", json=trade_payload, headers=trader_headers)
    trade_id = trade_resp.json()["id"]
    await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)

    await client.post(
        "/api/v1/market-data/quotes",
        json={"quote_date": "2026-01-10", "delivery_month": "2026-06-01", "price": 3.10},
        headers=trader_headers,
    )
    await client.post(
        "/api/v1/curves/build", json={"as_of_date": "2026-01-10"}, headers=trader_headers
    )
    return str(book.id)


@pytest.mark.asyncio
async def test_stress_test_default_scenarios(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)
    book_id = await _confirmed_book_with_curve(client, db_session, trader_headers, risk_headers)

    resp = await client.post(
        "/api/v1/risk/stress-test",
        json={"book_id": book_id, "as_of_date": "2026-01-10"},
        headers=risk_headers,
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 4  # DEFAULT_SCENARIOS
    # long 10,000 @ curve $3.10 -> +10% shock should be a positive P&L impact
    up_shock = next(r for r in results if r["scenario_name"] == "Parallel +10%")
    assert up_shock["pnl_impact"] == pytest.approx(10000 * 3.10 * 0.10)


@pytest.mark.asyncio
async def test_stress_test_custom_scenarios(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)
    book_id = await _confirmed_book_with_curve(client, db_session, trader_headers, risk_headers)

    resp = await client.post(
        "/api/v1/risk/stress-test",
        json={
            "book_id": book_id,
            "as_of_date": "2026-01-10",
            "scenarios": [
                {"name": "custom crash", "shock_type": "percentage", "shock_value": -0.25}
            ],
        },
        headers=risk_headers,
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 1
    assert results[0]["scenario_name"] == "custom crash"
    assert results[0]["pnl_impact"] < 0


@pytest.mark.asyncio
async def test_pnl_attribution_price_and_new_trade_effects(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)

    counterparty = Counterparty(name="Iota Trading")
    book = Book(name="Iota Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()
    book_id = str(book.id)

    # trade booked on the prior date, live on both snapshot dates
    old_trade = await client.post(
        "/api/v1/trades",
        json={
            "trade_date": "2026-01-05",
            "counterparty_id": str(counterparty.id),
            "book_id": book_id,
            "trade_type": "SWAP",
            "buy_sell": "BUY",
            "volume": 10000,
            "fixed_price": 3.00,
            "delivery_start_month": "2026-06-01",
            "delivery_end_month": "2026-06-01",
        },
        headers=trader_headers,
    )
    await client.post(f"/api/v1/trades/{old_trade.json()['id']}/confirm", headers=risk_headers)

    for as_of, price in [("2026-01-10", 3.10), ("2026-01-11", 3.15)]:
        await client.post(
            "/api/v1/market-data/quotes",
            json={"quote_date": as_of, "delivery_month": "2026-06-01", "price": price},
            headers=trader_headers,
        )
        build = await client.post(
            "/api/v1/curves/build", json={"as_of_date": as_of}, headers=trader_headers
        )
        assert build.status_code == 201

    # booked on the current date -- should be new_trade_effect, not price_effect
    new_trade = await client.post(
        "/api/v1/trades",
        json={
            "trade_date": "2026-01-11",
            "counterparty_id": str(counterparty.id),
            "book_id": book_id,
            "trade_type": "SWAP",
            "buy_sell": "BUY",
            "volume": 5000,
            "fixed_price": 3.05,
            "delivery_start_month": "2026-06-01",
            "delivery_end_month": "2026-06-01",
        },
        headers=trader_headers,
    )
    await client.post(f"/api/v1/trades/{new_trade.json()['id']}/confirm", headers=risk_headers)

    resp = await client.post(
        "/api/v1/risk/pnl-attribution",
        json={"book_id": book_id, "prior_date": "2026-01-10", "current_date": "2026-01-11"},
        headers=risk_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["price_effect"] == pytest.approx(10000 * (3.15 - 3.10))
    assert body["new_trade_effect"] == pytest.approx(5000 * (3.15 - 3.05))
    assert body["total"] == pytest.approx(body["price_effect"] + body["new_trade_effect"])
