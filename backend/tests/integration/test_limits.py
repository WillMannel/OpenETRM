import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.modules.trade_capture.models import Book, Counterparty
from tests.conftest import AuthHeadersFactory


async def _seed_book_and_counterparty(db_session: AsyncSession) -> tuple[str, str]:
    counterparty = Counterparty(name="Lambda Trading")
    book = Book(name="Lambda Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()
    return str(counterparty.id), str(book.id)


def _swap_payload(counterparty_id: str, book_id: str, volume: float, **overrides: object) -> dict:
    payload = {
        "trade_date": "2026-01-10",
        "counterparty_id": counterparty_id,
        "book_id": book_id,
        "trade_type": "SWAP",
        "buy_sell": "BUY",
        "volume": volume,
        "fixed_price": 3.00,
        "delivery_start_month": "2026-06-01",
        "delivery_end_month": "2026-06-01",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_create_limit_rejects_trader(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    _counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER)

    resp = await client.post(
        "/api/v1/limits",
        json={
            "book_id": book_id,
            "commodity": "HENRY_HUB",
            "limit_type": "VOLUME",
            "threshold": 5000,
        },
        headers=trader_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_volume_limit_blocks_confirm_over_threshold(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER, username="vol-limit-trader")
    risk_headers = await auth_headers(UserRole.RISK_MANAGER, username="vol-limit-risk")

    limit_resp = await client.post(
        "/api/v1/limits",
        json={
            "book_id": book_id,
            "commodity": "HENRY_HUB",
            "limit_type": "VOLUME",
            "threshold": 5000,
        },
        headers=risk_headers,
    )
    assert limit_resp.status_code == 201

    # within the limit -> confirms fine
    small_trade = await client.post(
        "/api/v1/trades", json=_swap_payload(counterparty_id, book_id, 4000), headers=trader_headers
    )
    small_trade_id = small_trade.json()["id"]
    confirm_small = await client.post(
        f"/api/v1/trades/{small_trade_id}/confirm", headers=risk_headers
    )
    assert confirm_small.status_code == 200

    # a second trade that would push net volume (4000 + 2000 = 6000) past the 5000 limit
    big_trade = await client.post(
        "/api/v1/trades", json=_swap_payload(counterparty_id, book_id, 2000), headers=trader_headers
    )
    big_trade_id = big_trade.json()["id"]
    confirm_big = await client.post(f"/api/v1/trades/{big_trade_id}/confirm", headers=risk_headers)
    assert confirm_big.status_code == 422
    assert "VOLUME limit" in confirm_big.json()["detail"]

    # the blocked trade stays NEW, not CONFIRMED
    trade_resp = await client.get(f"/api/v1/trades/{big_trade_id}", headers=trader_headers)
    assert trade_resp.json()["status"] == "NEW"

    # the breach was recorded and is visible to risk/admin
    breaches = await client.get("/api/v1/limits/breaches", headers=risk_headers)
    assert breaches.status_code == 200
    assert any(b["book_id"] == book_id and b["limit_type"] == "VOLUME" for b in breaches.json())


@pytest.mark.asyncio
async def test_var_limit_breach_is_recorded_but_does_not_block_the_run(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER, username="var-limit-trader")
    risk_headers = await auth_headers(UserRole.RISK_MANAGER, username="var-limit-risk")

    # a near-zero threshold guarantees any nonzero VaR breaches it
    limit_resp = await client.post(
        "/api/v1/limits",
        json={
            "book_id": book_id,
            "commodity": "HENRY_HUB",
            "limit_type": "VAR",
            "threshold": 0.0001,
            "confidence_level": 95,
        },
        headers=risk_headers,
    )
    assert limit_resp.status_code == 201

    trade_resp = await client.post(
        "/api/v1/trades",
        json=_swap_payload(counterparty_id, book_id, 10000),
        headers=trader_headers,
    )
    trade_id = trade_resp.json()["id"]
    await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)

    for quote_date, price in [("2026-01-08", 2.95), ("2026-01-09", 3.05), ("2026-01-10", 3.00)]:
        await client.post(
            "/api/v1/market-data/quotes",
            json={"quote_date": quote_date, "delivery_month": "2026-06-01", "price": price},
            headers=trader_headers,
        )
    await client.post(
        "/api/v1/curves/build", json={"as_of_date": "2026-01-10"}, headers=trader_headers
    )

    var_resp = await client.post(
        "/api/v1/risk/var/run",
        json={"book_id": book_id, "as_of_date": "2026-01-10", "confidence_level": 95},
        headers=risk_headers,
    )
    # the run itself always succeeds -- a VAR limit breach is informational, never blocking
    assert var_resp.status_code == 201

    breaches = await client.get(
        "/api/v1/limits/breaches", params={"book_id": book_id}, headers=risk_headers
    )
    assert breaches.status_code == 200
    open_breaches = [b for b in breaches.json() if b["limit_type"] == "VAR"]
    assert len(open_breaches) == 1
    breach_id = open_breaches[0]["id"]

    ack_resp = await client.post(
        f"/api/v1/limits/breaches/{breach_id}/acknowledge",
        json={"note": "reviewed, within trader's mandate"},
        headers=risk_headers,
    )
    assert ack_resp.status_code == 200
    assert ack_resp.json()["status"] == "ACKNOWLEDGED"

    breaches_after = await client.get(
        "/api/v1/limits/breaches", params={"book_id": book_id}, headers=risk_headers
    )
    assert all(b["limit_type"] != "VAR" for b in breaches_after.json())


@pytest.mark.asyncio
async def test_volume_limit_blocks_amendment_approval_over_threshold(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """Regression test: approving an amendment used to skip the VOLUME limit check
    entirely (only confirm_trade enforced it), so an amendment could blow through a
    limit that trade confirmation would have blocked."""
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER, username="amend-limit-trader")
    risk_headers = await auth_headers(UserRole.RISK_MANAGER, username="amend-limit-risk")

    limit_resp = await client.post(
        "/api/v1/limits",
        json={
            "book_id": book_id,
            "commodity": "HENRY_HUB",
            "limit_type": "VOLUME",
            "threshold": 5000,
        },
        headers=risk_headers,
    )
    assert limit_resp.status_code == 201

    trade_resp = await client.post(
        "/api/v1/trades", json=_swap_payload(counterparty_id, book_id, 4000), headers=trader_headers
    )
    trade_id = trade_resp.json()["id"]
    confirm_resp = await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)
    assert confirm_resp.status_code == 200

    # amend the confirmed trade's volume up past the limit
    amend_resp = await client.post(
        f"/api/v1/trades/{trade_id}/amendments",
        json={"changes": {"volume": 20000}, "reason": "counterparty wants a bigger clip"},
        headers=trader_headers,
    )
    assert amend_resp.status_code == 201
    change_request_id = amend_resp.json()["id"]

    approve_resp = await client.post(
        f"/api/v1/trade-change-requests/{change_request_id}/approve",
        json={},
        headers=risk_headers,
    )
    assert approve_resp.status_code == 422
    assert "VOLUME limit" in approve_resp.json()["detail"]

    # the blocked approval must not have applied the amendment: the trade is still
    # awaiting review (PENDING_AMENDMENT, same as before this approve attempt) at its
    # original volume -- not silently bumped to the over-limit value.
    trade_after = (await client.get(f"/api/v1/trades/{trade_id}", headers=trader_headers)).json()
    assert trade_after["status"] == "PENDING_AMENDMENT"
    assert trade_after["volume"] == 4000


@pytest.mark.asyncio
async def test_creating_limit_twice_updates_rather_than_duplicates(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    _counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)

    first = await client.post(
        "/api/v1/limits",
        json={
            "book_id": book_id,
            "commodity": "HENRY_HUB",
            "limit_type": "VOLUME",
            "threshold": 1000,
        },
        headers=risk_headers,
    )
    second = await client.post(
        "/api/v1/limits",
        json={
            "book_id": book_id,
            "commodity": "HENRY_HUB",
            "limit_type": "VOLUME",
            "threshold": 2000,
        },
        headers=risk_headers,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["threshold"] == 2000

    listed = await client.get("/api/v1/limits", params={"book_id": book_id}, headers=risk_headers)
    assert len(listed.json()) == 1
