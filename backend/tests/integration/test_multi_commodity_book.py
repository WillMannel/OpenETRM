"""Regression coverage for a real bug found in a code audit: a book holding trades in
more than one commodity in the same delivery month got netted together by
ValuationService.build_positions (which bucketed by delivery month alone, not
commodity), and RiskService's VaR/delta-ladder/stress/attribution/option-greeks paths
all had the same defect (each pulled *every* commodity's live trades for a book and
mixed them into one net-volume-by-month series). A book with 10,000 MMBtu of gas @
$3.00 and 500 MWh of power @ $45.00 in the same month, asked for POWER P&L against a
$50/MWh curve, returned a single HENRY_HUB-labeled position with net_volume=10500 and
avg_fixed_price=5.00 (gas volume and power volume summed as if they were the same
unit) and total_unrealized_pnl of $472,500 -- the correct, power-only answer is
$2,500. These tests pin the correct behavior: every valuation/risk surface must be
commodity-scoped, never mixing commodities within one number.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.modules.trade_capture.models import Book, Counterparty
from tests.conftest import AuthHeadersFactory


async def _seed(db_session: AsyncSession) -> tuple[str, str]:
    counterparty = Counterparty(name="Xi Multi-Commodity Trading")
    book = Book(name="Xi Mixed Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()
    return str(counterparty.id), str(book.id)


async def _book_gas_and_power(
    client: AsyncClient, cp_id: str, book_id: str, trader_headers: dict, risk_headers: dict
) -> tuple[str, str]:
    """Books 10,000 MMBtu of HENRY_HUB gas @ $3.00 and 500 MWh of POWER @ $45.00, both
    confirmed, both delivering June 2026. Returns (gas_trade_id, power_trade_id)."""
    gas = await client.post(
        "/api/v1/trades",
        json={
            "trade_date": "2026-01-10",
            "counterparty_id": cp_id,
            "book_id": book_id,
            "commodity": "HENRY_HUB",
            "trade_type": "SWAP",
            "buy_sell": "BUY",
            "volume": 10000,
            "volume_unit": "MMBTU",
            "fixed_price": 3.00,
            "delivery_start_month": "2026-06-01",
            "delivery_end_month": "2026-06-01",
        },
        headers=trader_headers,
    )
    assert gas.status_code == 201
    await client.post(f"/api/v1/trades/{gas.json()['id']}/confirm", headers=risk_headers)

    power = await client.post(
        "/api/v1/trades",
        json={
            "trade_date": "2026-01-10",
            "counterparty_id": cp_id,
            "book_id": book_id,
            "commodity": "POWER",
            "trade_type": "SWAP",
            "buy_sell": "BUY",
            "volume": 500,
            "volume_unit": "MWH",
            "fixed_price": 45.00,
            "delivery_start_month": "2026-06-01",
            "delivery_end_month": "2026-06-01",
            "power_block": "ON_PEAK",
        },
        headers=trader_headers,
    )
    assert power.status_code == 201
    await client.post(f"/api/v1/trades/{power.json()['id']}/confirm", headers=risk_headers)

    return gas.json()["id"], power.json()["id"]


@pytest.mark.asyncio
async def test_pnl_does_not_mix_commodities_in_the_same_delivery_month(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    cp_id, book_id = await _seed(db_session)
    trader = await auth_headers(UserRole.TRADER, username="mc-trader")
    risk = await auth_headers(UserRole.RISK_MANAGER, username="mc-risk")
    await _book_gas_and_power(client, cp_id, book_id, trader, risk)

    await client.post(
        "/api/v1/market-data/quotes",
        json={
            "quote_date": "2026-01-10",
            "delivery_month": "2026-06-01",
            "price": 50.00,
            "commodity": "POWER",
        },
        headers=trader,
    )
    await client.post(
        "/api/v1/curves/build",
        json={"as_of_date": "2026-01-10", "commodity": "POWER"},
        headers=trader,
    )

    pnl = await client.get(
        f"/api/v1/positions/{book_id}/pnl",
        params={"as_of_date": "2026-01-10", "commodity": "POWER"},
        headers=trader,
    )
    assert pnl.status_code == 200
    body = pnl.json()

    # Exactly one position -- the power leg -- must appear, not a merged gas+power row.
    assert len(body["positions"]) == 1
    position = body["positions"][0]
    assert position["commodity"] == "POWER"
    assert position["net_volume"] == pytest.approx(500.0)
    assert position["avg_fixed_price"] == pytest.approx(45.00)

    # long 500 MWh @ $45, curve at $50 -> +$5/MWh * 500 = $2,500. The gas leg (worth
    # 10000 * ($? - $3.00), no HENRY_HUB curve even published here) must not appear.
    assert body["total_unrealized_pnl"] == pytest.approx(500 * (50.00 - 45.00))


@pytest.mark.asyncio
async def test_var_run_does_not_mix_commodities(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    cp_id, book_id = await _seed(db_session)
    trader = await auth_headers(UserRole.TRADER, username="mc-var-trader")
    risk = await auth_headers(UserRole.RISK_MANAGER, username="mc-var-risk")
    await _book_gas_and_power(client, cp_id, book_id, trader, risk)

    # Only a POWER price history -- a HENRY_HUB VaR run must see zero net volume in
    # this month (the gas trade must not leak into the power net-volume series).
    for quote_date, price in [("2026-01-08", 49.0), ("2026-01-09", 51.0), ("2026-01-10", 50.0)]:
        await client.post(
            "/api/v1/market-data/quotes",
            json={
                "quote_date": quote_date,
                "delivery_month": "2026-06-01",
                "price": price,
                "commodity": "POWER",
            },
            headers=trader,
        )
    await client.post(
        "/api/v1/curves/build",
        json={"as_of_date": "2026-01-10", "commodity": "POWER"},
        headers=trader,
    )

    var_resp = await client.post(
        "/api/v1/risk/var/run",
        json={
            "book_id": book_id,
            "as_of_date": "2026-01-10",
            "commodity": "POWER",
            "confidence_level": 95,
        },
        headers=risk,
    )
    assert var_resp.status_code == 201
    # VaR should reflect only the 500 MWh power position against power price moves --
    # not the 10,000 MMBtu gas position (a ~20x larger volume) leaking in.
    # Max daily move here is $1/MWh on 500 MWh = $500 -- a VaR an order of magnitude
    # above that would indicate gas volume leaked into the power VaR calc.
    assert var_resp.json()["var_value"] < 1000


@pytest.mark.asyncio
async def test_volume_limit_is_scoped_to_its_own_commodity(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """A large, already-confirmed HENRY_HUB position must not count toward a POWER
    VOLUME limit -- the pre-fix behavior mixed every commodity's live trades into one
    net-volume-by-month series before taking the max against the limit, so a big gas
    position could wrongly block confirmation of a small, unrelated power trade."""
    cp_id, book_id = await _seed(db_session)
    trader = await auth_headers(UserRole.TRADER, username="mc-limit-trader")
    risk = await auth_headers(UserRole.RISK_MANAGER, username="mc-limit-risk")

    # A large, unconstrained (no gas limit configured) confirmed gas position.
    gas = await client.post(
        "/api/v1/trades",
        json={
            "trade_date": "2026-01-10",
            "counterparty_id": cp_id,
            "book_id": book_id,
            "commodity": "HENRY_HUB",
            "trade_type": "SWAP",
            "buy_sell": "BUY",
            "volume": 100000,
            "volume_unit": "MMBTU",
            "fixed_price": 3.00,
            "delivery_start_month": "2026-06-01",
            "delivery_end_month": "2026-06-01",
        },
        headers=trader,
    )
    assert gas.status_code == 201
    assert (
        await client.post(f"/api/v1/trades/{gas.json()['id']}/confirm", headers=risk)
    ).status_code == 200

    # A tight POWER limit -- comfortably above the power trade below (500) but many
    # times smaller than the gas position (100,000).
    limit_resp = await client.post(
        "/api/v1/limits",
        json={
            "book_id": book_id,
            "commodity": "POWER",
            "limit_type": "VOLUME",
            "threshold": 1000,
        },
        headers=risk,
    )
    assert limit_resp.status_code == 201

    # A modest power trade, well within the 1,000 POWER limit on its own -- must not
    # be blocked by the unrelated 100,000-unit gas position.
    power = await client.post(
        "/api/v1/trades",
        json={
            "trade_date": "2026-01-10",
            "counterparty_id": cp_id,
            "book_id": book_id,
            "commodity": "POWER",
            "trade_type": "SWAP",
            "buy_sell": "BUY",
            "volume": 500,
            "volume_unit": "MWH",
            "fixed_price": 45.00,
            "delivery_start_month": "2026-06-01",
            "delivery_end_month": "2026-06-01",
            "power_block": "ON_PEAK",
        },
        headers=trader,
    )
    assert power.status_code == 201
    confirm_resp = await client.post(f"/api/v1/trades/{power.json()['id']}/confirm", headers=risk)
    assert confirm_resp.status_code == 200


@pytest.mark.asyncio
async def test_pnl_attribution_does_not_mix_commodities(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    cp_id, book_id = await _seed(db_session)
    trader = await auth_headers(UserRole.TRADER, username="mc-attr-trader")
    risk = await auth_headers(UserRole.RISK_MANAGER, username="mc-attr-risk")
    await _book_gas_and_power(client, cp_id, book_id, trader, risk)

    for as_of, price in [("2026-01-10", 50.00), ("2026-01-11", 52.00)]:
        await client.post(
            "/api/v1/market-data/quotes",
            json={
                "quote_date": as_of,
                "delivery_month": "2026-06-01",
                "price": price,
                "commodity": "POWER",
            },
            headers=trader,
        )
        build = await client.post(
            "/api/v1/curves/build",
            json={"as_of_date": as_of, "commodity": "POWER"},
            headers=trader,
        )
        assert build.status_code == 201

    resp = await client.post(
        "/api/v1/risk/pnl-attribution",
        json={
            "book_id": book_id,
            "prior_date": "2026-01-10",
            "current_date": "2026-01-11",
            "commodity": "POWER",
        },
        headers=risk,
    )
    assert resp.status_code == 200
    body = resp.json()
    # 500 MWh * ($52 - $50) = $1,000 -- if the 10,000 MMBtu gas position leaked in,
    # this would be off by roughly 20x.
    assert body["price_effect"] == pytest.approx(500 * (52.00 - 50.00))
