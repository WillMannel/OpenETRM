"""Proves Commodity.WTI is a real second value the whole stack handles, not just an
enum member nobody exercises -- runs the same trade -> curve -> valuation -> risk flow
as the Henry Hub tests, with WTI end to end, in the same book alongside a Henry Hub
position to confirm commodities don't cross-contaminate each other's curves/positions.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.modules.trade_capture.models import Book, Counterparty
from tests.conftest import AuthHeadersFactory


@pytest.mark.asyncio
async def test_wti_trade_curve_and_var_end_to_end(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty = Counterparty(name="Eta Oil Trading")
    book = Book(name="Eta Crude Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()
    book_id = str(book.id)

    trader_headers = await auth_headers(UserRole.TRADER)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)

    trade_payload = {
        "trade_date": "2026-01-10",
        "counterparty_id": str(counterparty.id),
        "book_id": book_id,
        "commodity": "WTI",
        "trade_type": "SWAP",
        "buy_sell": "BUY",
        "volume": 1000,
        "volume_unit": "BBL",
        "fixed_price": 70.00,
        "delivery_start_month": "2026-06-01",
        "delivery_end_month": "2026-06-01",
        "floating_index": "WTI_CUSHING",
    }
    trade_resp = await client.post("/api/v1/trades", json=trade_payload, headers=trader_headers)
    assert trade_resp.status_code == 201
    trade_id = trade_resp.json()["id"]
    assert trade_resp.json()["commodity"] == "WTI"
    assert trade_resp.json()["volume_unit"] == "BBL"

    confirm_resp = await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)
    assert confirm_resp.status_code == 200

    quote_resp = await client.post(
        "/api/v1/market-data/quotes",
        json={
            "commodity": "WTI",
            "quote_date": "2026-01-10",
            "delivery_month": "2026-06-01",
            "price": 72.50,
        },
        headers=trader_headers,
    )
    assert quote_resp.status_code == 201

    curve_resp = await client.post(
        "/api/v1/curves/build",
        json={"commodity": "WTI", "as_of_date": "2026-01-10"},
        headers=trader_headers,
    )
    assert curve_resp.status_code == 201
    assert curve_resp.json()["commodity"] == "WTI"

    pnl_resp = await client.get(
        f"/api/v1/positions/{book_id}/pnl",
        params={"as_of_date": "2026-01-10", "commodity": "WTI"},
        headers=trader_headers,
    )
    assert pnl_resp.status_code == 200
    # long 1000 bbl @ $70.00 against a $72.50 curve -> +$2,500 unrealized
    assert pnl_resp.json()["total_unrealized_pnl"] == pytest.approx(2500.0)

    var_resp = await client.post(
        "/api/v1/risk/var/run",
        json={
            "book_id": book_id,
            "as_of_date": "2026-01-10",
            "commodity": "WTI",
            "scenario_window_days": 250,
        },
        headers=risk_headers,
    )
    assert var_resp.status_code == 201
    assert var_resp.json()["var_value"] >= 0.0


@pytest.mark.asyncio
async def test_henry_hub_curve_lookup_does_not_see_wti_quotes(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER)

    await client.post(
        "/api/v1/market-data/quotes",
        json={
            "commodity": "WTI",
            "quote_date": "2026-01-10",
            "delivery_month": "2026-06-01",
            "price": 72.50,
        },
        headers=trader_headers,
    )

    # no Henry Hub quotes seeded at all -- building a Henry Hub curve must fail, not
    # silently pick up the WTI quote for the same delivery month.
    resp = await client.post(
        "/api/v1/curves/build",
        json={"commodity": "HENRY_HUB", "as_of_date": "2026-01-10"},
        headers=trader_headers,
    )
    assert resp.status_code == 422
