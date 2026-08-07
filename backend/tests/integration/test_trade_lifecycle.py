import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.modules.trade_capture.models import Book, Counterparty
from tests.conftest import AuthHeadersFactory


async def _seed_book_and_counterparty(db_session: AsyncSession) -> tuple[str, str]:
    counterparty = Counterparty(name="Zeta Trading LLC")
    book = Book(name="Zeta Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()
    return str(counterparty.id), str(book.id)


async def _book_confirmed_trade(
    client: AsyncClient,
    counterparty_id: str,
    book_id: str,
    trader_headers: dict,
    risk_headers: dict,
) -> str:
    payload = {
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
    create_resp = await client.post("/api/v1/trades", json=payload, headers=trader_headers)
    assert create_resp.status_code == 201
    trade_id = create_resp.json()["id"]

    confirm_resp = await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)
    assert confirm_resp.status_code == 200
    return trade_id


@pytest.mark.asyncio
async def test_confirm_requires_new_status(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER)
    risk_headers = await auth_headers(UserRole.RISK_MANAGER)

    trade_id = await _book_confirmed_trade(
        client, counterparty_id, book_id, trader_headers, risk_headers
    )

    # already CONFIRMED -- confirming again must fail
    resp = await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_confirm_rejects_trader_role(
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
        "volume": 10000,
        "fixed_price": 3.00,
        "delivery_start_month": "2026-06-01",
        "delivery_end_month": "2026-06-01",
    }
    create_resp = await client.post("/api/v1/trades", json=payload, headers=trader_headers)
    trade_id = create_resp.json()["id"]

    # confirming is a middle-office/risk function -- a trader may not do it
    resp = await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=trader_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_amendment_approval_creates_new_version_and_supersedes_old(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER, username="amend-trader")
    risk_headers = await auth_headers(UserRole.RISK_MANAGER, username="amend-approver")

    trade_id = await _book_confirmed_trade(
        client, counterparty_id, book_id, trader_headers, risk_headers
    )

    amend_resp = await client.post(
        f"/api/v1/trades/{trade_id}/amendments",
        json={"changes": {"volume": 15000}, "reason": "counterparty requested a larger clip"},
        headers=trader_headers,
    )
    assert amend_resp.status_code == 201
    change_request_id = amend_resp.json()["id"]
    assert amend_resp.json()["status"] == "PENDING"

    # the original trade is now PENDING_AMENDMENT, not CONFIRMED
    trade_resp = await client.get(f"/api/v1/trades/{trade_id}", headers=trader_headers)
    assert trade_resp.json()["status"] == "PENDING_AMENDMENT"

    approve_resp = await client.post(
        f"/api/v1/trade-change-requests/{change_request_id}/approve",
        json={"note": "looks right"},
        headers=risk_headers,
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "APPROVED"

    old_trade = (await client.get(f"/api/v1/trades/{trade_id}", headers=trader_headers)).json()
    assert old_trade["status"] == "AMENDED"

    # find the new version via the book's trade list
    all_trades = (
        await client.get("/api/v1/trades", params={"book_id": book_id}, headers=trader_headers)
    ).json()
    new_trade = next(t for t in all_trades if t["previous_version_id"] == trade_id)
    assert new_trade["status"] == "CONFIRMED"
    assert new_trade["version"] == 2
    assert new_trade["volume"] == 15000
    assert new_trade["fixed_price"] == 3.00  # unchanged fields carry over


@pytest.mark.asyncio
async def test_four_eyes_rejects_self_approval(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    # ADMIN can both request (TRADER_OR_ADMIN) and approve (RISK_OR_ADMIN) -- the only
    # role that can hit both endpoints, needed to exercise the same-user case at all.
    admin_headers = await auth_headers(UserRole.ADMIN, username="self-approve-admin")

    trade_id = await _book_confirmed_trade(
        client, counterparty_id, book_id, admin_headers, admin_headers
    )

    cancel_resp = await client.post(
        f"/api/v1/trades/{trade_id}/cancellations",
        json={"reason": "booked in error"},
        headers=admin_headers,
    )
    assert cancel_resp.status_code == 201
    change_request_id = cancel_resp.json()["id"]

    # the SAME user tries to approve their own request -- four-eyes must block this
    # even though their role alone would otherwise be allowed to approve.
    approve_resp = await client.post(
        f"/api/v1/trade-change-requests/{change_request_id}/approve",
        json={},
        headers=admin_headers,
    )
    assert approve_resp.status_code == 422
    assert "four-eyes" in approve_resp.json()["detail"]


@pytest.mark.asyncio
async def test_cancellation_rejected_reverts_trade_to_confirmed(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER, username="reject-trader")
    risk_headers_a = await auth_headers(UserRole.RISK_MANAGER, username="reject-risk-a")
    risk_headers_b = await auth_headers(UserRole.RISK_MANAGER, username="reject-risk-b")

    trade_id = await _book_confirmed_trade(
        client, counterparty_id, book_id, trader_headers, risk_headers_a
    )

    cancel_resp = await client.post(
        f"/api/v1/trades/{trade_id}/cancellations",
        json={"reason": "wrong counterparty"},
        headers=trader_headers,
    )
    change_request_id = cancel_resp.json()["id"]

    reject_resp = await client.post(
        f"/api/v1/trade-change-requests/{change_request_id}/reject",
        json={"note": "counterparty is correct, keep the trade"},
        headers=risk_headers_b,
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "REJECTED"

    trade_resp = await client.get(f"/api/v1/trades/{trade_id}", headers=trader_headers)
    assert trade_resp.json()["status"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_audit_log_records_the_full_lifecycle(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER, username="audit-trader")
    risk_headers = await auth_headers(UserRole.RISK_MANAGER, username="audit-risk")

    trade_id = await _book_confirmed_trade(
        client, counterparty_id, book_id, trader_headers, risk_headers
    )

    history_resp = await client.get(f"/api/v1/audit/Trade/{trade_id}", headers=trader_headers)
    assert history_resp.status_code == 200
    actions = [entry["action"] for entry in history_resp.json()]
    assert actions == ["CREATE", "CONFIRM"]
    assert history_resp.json()[0]["after"]["status"] == "NEW"
    assert history_resp.json()[1]["before"]["status"] == "NEW"
    assert history_resp.json()[1]["after"]["status"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_pending_change_requests_only_visible_to_risk_or_admin(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty_id, book_id = await _seed_book_and_counterparty(db_session)
    trader_headers = await auth_headers(UserRole.TRADER, username="pending-trader")
    risk_headers = await auth_headers(UserRole.RISK_MANAGER, username="pending-risk")

    trade_id = await _book_confirmed_trade(
        client, counterparty_id, book_id, trader_headers, risk_headers
    )
    await client.post(
        f"/api/v1/trades/{trade_id}/cancellations", json={"reason": "test"}, headers=trader_headers
    )

    trader_view = await client.get("/api/v1/trade-change-requests", headers=trader_headers)
    assert trader_view.status_code == 403

    risk_view = await client.get("/api/v1/trade-change-requests", headers=risk_headers)
    assert risk_view.status_code == 200
    assert any(cr["trade_id"] == trade_id for cr in risk_view.json())
