import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.modules.trade_capture.models import Book, Counterparty
from tests.conftest import AuthHeadersFactory


async def _seed_book_and_counterparty(db_session: AsyncSession) -> tuple[str, str]:
    counterparty = Counterparty(name="Gamma Trading LLC")
    book = Book(name="Gamma Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()
    return str(counterparty.id), str(book.id)


@pytest.mark.asyncio
async def test_full_vertical_slice_trade_to_var(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)

    # 1. capture a trade: long 10,000 MMBtu at $3.00 for June 2026 -- starts as NEW
    trade_payload = {
        "trade_date": "2026-01-10",
        "counterparty_id": counterparty_id,
        "book_id": book_id,
        "trade_type": "SWAP",
        "buy_sell": "BUY",
        "volume": 10000,
        "fixed_price": 3.00,
        "delivery_start_month": "2026-06-01",
        "delivery_end_month": "2026-06-01",
    }
    trade_resp = await client.post("/api/v1/trades", json=trade_payload, headers=trader_headers)
    assert trade_resp.status_code == 201
    trade_id = trade_resp.json()["id"]
    assert trade_resp.json()["status"] == "NEW"

    # 2. seed a couple of days of market data and bootstrap the curve
    for quote_date, price in [("2026-01-08", 3.05), ("2026-01-09", 3.15), ("2026-01-10", 3.10)]:
        resp = await client.post(
            "/api/v1/market-data/quotes",
            json={"quote_date": quote_date, "delivery_month": "2026-06-01", "price": price},
            headers=trader_headers,
        )
        assert resp.status_code == 201
    curve_resp = await client.post(
        "/api/v1/curves/build", json={"as_of_date": "2026-01-10"}, headers=trader_headers
    )
    assert curve_resp.status_code == 201

    # 3. a NEW (unconfirmed) trade must not move the book's P&L
    pnl_while_new = await client.get(
        f"/api/v1/positions/{book_id}/pnl",
        params={"as_of_date": "2026-01-10"},
        headers=trader_headers,
    )
    assert pnl_while_new.status_code == 200
    assert pnl_while_new.json()["total_unrealized_pnl"] == 0.0
    assert pnl_while_new.json()["positions"] == []

    # 4. confirm it (a middle-office/risk function, not the trader who booked it)
    confirm_resp = await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "CONFIRMED"

    # 5. now it counts: long 10,000 @ $3.00 against a $3.10 curve -> +$1,000 unrealized
    pnl_resp = await client.get(
        f"/api/v1/positions/{book_id}/pnl",
        params={"as_of_date": "2026-01-10"},
        headers=trader_headers,
    )
    assert pnl_resp.status_code == 200
    assert pnl_resp.json()["total_unrealized_pnl"] == pytest.approx(1000.0)

    # 6. VaR run should succeed and return a nonnegative loss figure
    var_resp = await client.post(
        "/api/v1/risk/var/run",
        json={
            "book_id": book_id,
            "as_of_date": "2026-01-10",
            "confidence_level": 95,
            "scenario_window_days": 250,
        },
        headers=risk_headers,
    )
    assert var_resp.status_code == 201
    assert var_resp.json()["var_value"] >= 0.0

    # 7. delta ladder should attribute all delta to the June 2026 bucket
    ladder_resp = await client.get(
        "/api/v1/risk/delta-ladder",
        params={"book_id": book_id, "as_of_date": "2026-01-10"},
        headers=risk_headers,
    )
    assert ladder_resp.status_code == 200
    buckets = ladder_resp.json()["buckets"]
    assert len(buckets) == 1
    assert buckets[0]["tenor_bucket"] == "2026-06"
    assert buckets[0]["delta_value"] == pytest.approx(10000.0)
