import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.modules.trade_capture.models import Book, Counterparty
from tests.conftest import AuthHeadersFactory


async def _seed_book_and_counterparty(db_session: AsyncSession) -> tuple[str, str]:
    counterparty = Counterparty(name="Mu Power Trading")
    book = Book(name="Mu Power Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()
    return str(counterparty.id), str(book.id)


def _power_swap_payload(counterparty_id: str, book_id: str, **overrides: object) -> dict:
    payload = {
        "trade_date": "2026-01-10",
        "counterparty_id": counterparty_id,
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
    }
    payload.update(overrides)
    return payload


def _rec_payload(counterparty_id: str, book_id: str, **overrides: object) -> dict:
    payload = {
        "trade_date": "2026-01-10",
        "counterparty_id": counterparty_id,
        "book_id": book_id,
        "commodity": "POWER",
        "trade_type": "REC",
        "buy_sell": "BUY",
        "volume": 1000,
        "volume_unit": "MWH",
        "fixed_price": 12.50,
        "delivery_start_month": "2026-01-01",
        "delivery_end_month": "2026-12-01",
        "certificate_registry": "WREGIS",
        "vintage_year": 2026,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_coal_trade_uses_the_same_generic_pipeline_as_gas_and_oil(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """No commodity-specific code exists for COAL -- it's a smoke test that adding a
    new Commodity value really is just an enum addition, same as WTI was."""
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER)

    resp = await client.post(
        "/api/v1/trades",
        json={
            "trade_date": "2026-01-10",
            "counterparty_id": counterparty_id,
            "book_id": book_id,
            "commodity": "COAL",
            "trade_type": "SWAP",
            "buy_sell": "BUY",
            "volume": 5000,
            "volume_unit": "METRIC_TON",
            "fixed_price": 90.00,
            "delivery_start_month": "2026-06-01",
            "delivery_end_month": "2026-06-01",
        },
        headers=trader_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["commodity"] == "COAL"


@pytest.mark.asyncio
async def test_power_trade_requires_power_block(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER)

    payload = _power_swap_payload(counterparty_id, book_id)
    del payload["power_block"]
    resp = await client.post("/api/v1/trades", json=payload, headers=trader_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_power_block_rejected_on_non_power_commodity(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER)

    resp = await client.post(
        "/api/v1/trades",
        json={
            "trade_date": "2026-01-10",
            "counterparty_id": counterparty_id,
            "book_id": book_id,
            "commodity": "HENRY_HUB",
            "trade_type": "SWAP",
            "buy_sell": "BUY",
            "volume": 10000,
            "fixed_price": 3.00,
            "delivery_start_month": "2026-06-01",
            "delivery_end_month": "2026-06-01",
            "power_block": "ON_PEAK",
        },
        headers=trader_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_power_swap_confirms_and_marks_to_market_like_any_swap(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER, username="power-trader")
    risk_headers = await auth_headers(UserRole.RISK_MANAGER, username="power-risk")

    create_resp = await client.post(
        "/api/v1/trades", json=_power_swap_payload(counterparty_id, book_id), headers=trader_headers
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["power_block"] == "ON_PEAK"
    trade_id = create_resp.json()["id"]

    confirm_resp = await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)
    assert confirm_resp.status_code == 200

    await client.post(
        "/api/v1/market-data/quotes",
        json={
            "quote_date": "2026-01-10",
            "delivery_month": "2026-06-01",
            "price": 50.00,
            "commodity": "POWER",
        },
        headers=trader_headers,
    )
    build_resp = await client.post(
        "/api/v1/curves/build",
        json={"as_of_date": "2026-01-10", "commodity": "POWER"},
        headers=trader_headers,
    )
    assert build_resp.status_code == 201

    pnl_resp = await client.get(
        f"/api/v1/positions/{book_id}/pnl",
        params={"as_of_date": "2026-01-10", "commodity": "POWER"},
        headers=trader_headers,
    )
    assert pnl_resp.status_code == 200
    body = pnl_resp.json()
    assert len(body["positions"]) == 1
    # long 500 MWh @ $45, curve at $50 -> +$5/MWh * 500 = $2500 unrealized
    assert body["total_unrealized_pnl"] == pytest.approx(500 * (50.00 - 45.00))


@pytest.mark.asyncio
async def test_rec_trade_requires_registry_and_vintage_year(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER)

    payload = _rec_payload(counterparty_id, book_id)
    del payload["certificate_registry"]
    resp = await client.post("/api/v1/trades", json=payload, headers=trader_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_rec_trade_lifecycle_but_excluded_from_valuation(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """RECs go through the full capture/confirm/audit lifecycle like any other trade,
    but v1 has no curve-based valuation for them (LINEAR_TRADE_TYPES) -- confirm this
    doesn't silently corrupt a book's SWAP positions when both are booked together."""
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER, username="rec-trader")
    risk_headers = await auth_headers(UserRole.RISK_MANAGER, username="rec-risk")

    rec_resp = await client.post(
        "/api/v1/trades", json=_rec_payload(counterparty_id, book_id), headers=trader_headers
    )
    assert rec_resp.status_code == 201
    rec_trade_id = rec_resp.json()["id"]
    assert rec_resp.json()["fixed_price"] == pytest.approx(12.50)

    confirm_resp = await client.post(f"/api/v1/trades/{rec_trade_id}/confirm", headers=risk_headers)
    assert confirm_resp.status_code == 200

    history_resp = await client.get(f"/api/v1/audit/Trade/{rec_trade_id}", headers=trader_headers)
    assert [e["action"] for e in history_resp.json()] == ["CREATE", "CONFIRM"]

    # book alongside an ordinary POWER swap and confirm the REC doesn't leak into positions
    swap_resp = await client.post(
        "/api/v1/trades", json=_power_swap_payload(counterparty_id, book_id), headers=trader_headers
    )
    await client.post(f"/api/v1/trades/{swap_resp.json()['id']}/confirm", headers=risk_headers)

    await client.post(
        "/api/v1/market-data/quotes",
        json={
            "quote_date": "2026-01-10",
            "delivery_month": "2026-06-01",
            "price": 50.00,
            "commodity": "POWER",
        },
        headers=trader_headers,
    )
    await client.post(
        "/api/v1/curves/build",
        json={"as_of_date": "2026-01-10", "commodity": "POWER"},
        headers=trader_headers,
    )
    pnl_resp = await client.get(
        f"/api/v1/positions/{book_id}/pnl",
        params={"as_of_date": "2026-01-10", "commodity": "POWER"},
        headers=trader_headers,
    )
    # exactly one position (the swap's June bucket) -- the REC's Jan-Dec vintage
    # window never contributes a position
    assert len(pnl_resp.json()["positions"]) == 1


@pytest.mark.asyncio
async def test_emissions_allowance_trade_lifecycle(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER, username="emissions-trader")
    risk_headers = await auth_headers(UserRole.RISK_MANAGER, username="emissions-risk")

    payload = _rec_payload(
        counterparty_id,
        book_id,
        trade_type="EMISSIONS_ALLOWANCE",
        certificate_registry="RGGI",
        volume_unit="METRIC_TON",
        fixed_price=15.75,
    )
    resp = await client.post("/api/v1/trades", json=payload, headers=trader_headers)
    assert resp.status_code == 201
    assert resp.json()["certificate_registry"] == "RGGI"

    confirm_resp = await client.post(
        f"/api/v1/trades/{resp.json()['id']}/confirm", headers=risk_headers
    )
    assert confirm_resp.status_code == 200
