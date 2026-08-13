import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.modules.trade_capture.models import Book, Counterparty
from tests.conftest import AuthHeadersFactory


async def _seed_book_and_counterparty(db_session: AsyncSession) -> tuple[str, str]:
    counterparty = Counterparty(name="Kappa Trading")
    book = Book(name="Kappa Options Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()
    return str(counterparty.id), str(book.id)


def _option_payload(counterparty_id: str, book_id: str, **overrides: object) -> dict:
    payload = {
        "trade_date": "2026-01-10",
        "counterparty_id": counterparty_id,
        "book_id": book_id,
        "trade_type": "OPTION",
        "buy_sell": "BUY",
        "volume": 1000,
        "delivery_start_month": "2026-06-01",
        "delivery_end_month": "2026-06-01",
        "option_type": "CALL",
        "strike_price": 3.00,
        "premium": 0.20,
        "option_volatility": 0.35,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_option_trade_requires_option_fields(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER)

    payload = _option_payload(counterparty_id, book_id)
    del payload["strike_price"]
    resp = await client.post("/api/v1/trades", json=payload, headers=trader_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_swap_trade_rejects_option_fields(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER)

    payload = {
        "trade_date": "2026-01-10",
        "counterparty_id": counterparty_id,
        "book_id": book_id,
        "trade_type": "SWAP",
        "buy_sell": "BUY",
        "volume": 1000,
        "fixed_price": 3.00,
        "delivery_start_month": "2026-06-01",
        "delivery_end_month": "2026-06-01",
        "strike_price": 3.00,
    }
    resp = await client.post("/api/v1/trades", json=payload, headers=trader_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_option_trade_create_confirm_and_value(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)

    create_resp = await client.post(
        "/api/v1/trades", json=_option_payload(counterparty_id, book_id), headers=trader_headers
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["fixed_price"] is None
    assert body["strike_price"] == pytest.approx(3.00)
    trade_id = body["id"]

    confirm_resp = await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)
    assert confirm_resp.status_code == 200

    # forward well above strike -> an in-the-money call should have positive MTM
    await client.post(
        "/api/v1/market-data/quotes",
        json={"quote_date": "2026-01-10", "delivery_month": "2026-06-01", "price": 4.00},
        headers=trader_headers,
    )
    build_resp = await client.post(
        "/api/v1/curves/build", json={"as_of_date": "2026-01-10"}, headers=trader_headers
    )
    assert build_resp.status_code == 201

    pnl_resp = await client.get(
        f"/api/v1/positions/{book_id}/pnl",
        params={"as_of_date": "2026-01-10"},
        headers=trader_headers,
    )
    assert pnl_resp.status_code == 200
    pnl_body = pnl_resp.json()
    # the option leg doesn't roll into `positions` (non-linear payoff), but does
    # contribute to total_mtm_value/total_unrealized_pnl via its own ValuationResult
    assert pnl_body["positions"] == []
    assert pnl_body["total_mtm_value"] > 0


@pytest.mark.asyncio
async def test_option_greeks_endpoint(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)

    create_resp = await client.post(
        "/api/v1/trades", json=_option_payload(counterparty_id, book_id), headers=trader_headers
    )
    trade_id = create_resp.json()["id"]
    await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)

    await client.post(
        "/api/v1/market-data/quotes",
        json={"quote_date": "2026-01-10", "delivery_month": "2026-06-01", "price": 3.20},
        headers=trader_headers,
    )
    await client.post(
        "/api/v1/curves/build", json={"as_of_date": "2026-01-10"}, headers=trader_headers
    )

    resp = await client.post(
        "/api/v1/risk/options/greeks",
        json={"book_id": book_id, "as_of_date": "2026-01-10"},
        headers=risk_headers,
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 1
    assert results[0]["trade_id"] == trade_id
    assert 0.0 < results[0]["delta"] < 1.0  # long call


@pytest.mark.asyncio
async def test_amendment_cannot_set_a_non_positive_strike_price(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """Regression test: TradeCreate rejects strike_price<=0 at trade creation, but
    amendments went through a separate code path that skipped this check entirely."""
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER, username="neg-strike-trader")
    risk_headers = await auth_headers(UserRole.RISK_MANAGER, username="neg-strike-risk")

    create_resp = await client.post(
        "/api/v1/trades", json=_option_payload(counterparty_id, book_id), headers=trader_headers
    )
    trade_id = create_resp.json()["id"]
    await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)

    resp = await client.post(
        f"/api/v1/trades/{trade_id}/amendments",
        json={"changes": {"strike_price": -5}, "reason": "fat-fingered strike"},
        headers=trader_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_option_greeks_endpoint_rejects_trader(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    _counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER)

    resp = await client.post(
        "/api/v1/risk/options/greeks",
        json={"book_id": book_id, "as_of_date": "2026-01-10"},
        headers=trader_headers,
    )
    assert resp.status_code == 403
