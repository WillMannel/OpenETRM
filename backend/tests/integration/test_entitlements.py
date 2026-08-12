"""Book-level entitlements (desk separation / "Chinese walls").

A book is unrestricted (today's pre-existing behavior: any authenticated user with the
right role may act on it) until it's assigned to a Desk. Once assigned, only ADMIN or a
user with an explicit BookMembership grant for that book may see or act on it -- across
trade capture, valuation, risk, limits, and export. These tests prove the wall actually
holds on every one of those surfaces, that granting/revoking membership actually
flips access, that un-assigning a desk restores the pre-existing unrestricted
behavior, and that the entitlement-management endpoints themselves are ADMIN-only.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.modules.auth.models import User
from app.modules.trade_capture.models import Book, Counterparty
from tests.conftest import AuthHeadersFactory


async def _user_id(db_session: AsyncSession, username: str) -> str:
    user = (await db_session.execute(select(User).where(User.username == username))).scalar_one()
    return str(user.id)


async def _seed_restricted_book(
    client: AsyncClient, db_session: AsyncSession, admin_headers: dict
) -> tuple[str, str]:
    """Creates a counterparty + book, a desk, and assigns the book to the desk (turning
    on entitlement enforcement). Returns (counterparty_id, book_id)."""
    counterparty = Counterparty(name="Sigma Walled Trading")
    book = Book(name="Sigma Walled Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()

    desk_resp = await client.post(
        "/api/v1/desks", json={"name": "Sigma Gas Desk"}, headers=admin_headers
    )
    assert desk_resp.status_code == 201
    desk_id = desk_resp.json()["id"]

    assign_resp = await client.put(
        f"/api/v1/books/{book.id}/desk", json={"desk_id": desk_id}, headers=admin_headers
    )
    assert assign_resp.status_code == 204

    return str(counterparty.id), str(book.id)


async def _grant(client: AsyncClient, book_id: str, user_id: str, admin_headers: dict) -> None:
    resp = await client.post(
        f"/api/v1/books/{book_id}/members", json={"user_id": user_id}, headers=admin_headers
    )
    assert resp.status_code == 201


def _trade_payload(cp_id: str, book_id: str) -> dict:
    return {
        "trade_date": "2026-01-10",
        "counterparty_id": cp_id,
        "book_id": book_id,
        "trade_type": "SWAP",
        "buy_sell": "BUY",
        "volume": 1000,
        "fixed_price": 3.00,
        "delivery_start_month": "2026-06-01",
        "delivery_end_month": "2026-06-01",
    }


@pytest.mark.asyncio
async def test_outsider_cannot_book_a_trade_into_a_walled_book(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    admin = await auth_headers(UserRole.ADMIN, username="wall-admin-1")
    outsider = await auth_headers(UserRole.TRADER, username="wall-outsider-1")
    cp_id, book_id = await _seed_restricted_book(client, db_session, admin)

    resp = await client.post(
        "/api/v1/trades", json=_trade_payload(cp_id, book_id), headers=outsider
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_member_can_book_a_trade_into_their_walled_book(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    admin = await auth_headers(UserRole.ADMIN, username="wall-admin-2")
    member = await auth_headers(UserRole.TRADER, username="wall-member-2")
    cp_id, book_id = await _seed_restricted_book(client, db_session, admin)
    await _grant(client, book_id, await _user_id(db_session, "wall-member-2"), admin)

    resp = await client.post("/api/v1/trades", json=_trade_payload(cp_id, book_id), headers=member)
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_admin_always_has_access_regardless_of_membership(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    admin = await auth_headers(UserRole.ADMIN, username="wall-admin-3")
    cp_id, book_id = await _seed_restricted_book(client, db_session, admin)

    resp = await client.post("/api/v1/trades", json=_trade_payload(cp_id, book_id), headers=admin)
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_outsider_cannot_see_the_trade_by_id_even_if_they_know_it(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    admin = await auth_headers(UserRole.ADMIN, username="wall-admin-4")
    outsider = await auth_headers(UserRole.TRADER, username="wall-outsider-4")
    cp_id, book_id = await _seed_restricted_book(client, db_session, admin)

    create_resp = await client.post(
        "/api/v1/trades", json=_trade_payload(cp_id, book_id), headers=admin
    )
    trade_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/trades/{trade_id}", headers=outsider)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_outsider_listing_trades_does_not_see_the_walled_books_trades(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    admin = await auth_headers(UserRole.ADMIN, username="wall-admin-5")
    outsider = await auth_headers(UserRole.TRADER, username="wall-outsider-5")
    cp_id, book_id = await _seed_restricted_book(client, db_session, admin)

    create_resp = await client.post(
        "/api/v1/trades", json=_trade_payload(cp_id, book_id), headers=admin
    )
    trade_id = create_resp.json()["id"]

    resp = await client.get("/api/v1/trades", headers=outsider)
    assert resp.status_code == 200
    assert trade_id not in [t["id"] for t in resp.json()]


@pytest.mark.asyncio
async def test_outsider_cannot_confirm_a_trade_in_a_walled_book(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    admin = await auth_headers(UserRole.ADMIN, username="wall-admin-6")
    outsider_risk = await auth_headers(UserRole.RISK_MANAGER, username="wall-outsider-risk-6")
    cp_id, book_id = await _seed_restricted_book(client, db_session, admin)

    create_resp = await client.post(
        "/api/v1/trades", json=_trade_payload(cp_id, book_id), headers=admin
    )
    trade_id = create_resp.json()["id"]

    resp = await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=outsider_risk)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_outsider_cannot_get_pnl_for_a_walled_book(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    admin = await auth_headers(UserRole.ADMIN, username="wall-admin-7")
    outsider = await auth_headers(UserRole.TRADER, username="wall-outsider-7")
    _cp_id, book_id = await _seed_restricted_book(client, db_session, admin)

    resp = await client.get(
        f"/api/v1/positions/{book_id}/pnl", params={"as_of_date": "2026-01-10"}, headers=outsider
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_outsider_cannot_create_a_valuation_run_for_a_walled_book(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    admin = await auth_headers(UserRole.ADMIN, username="wall-admin-8")
    outsider_risk = await auth_headers(UserRole.RISK_MANAGER, username="wall-outsider-risk-8")
    _cp_id, book_id = await _seed_restricted_book(client, db_session, admin)

    resp = await client.post(
        f"/api/v1/positions/{book_id}/valuation-runs",
        json={"as_of_date": "2026-01-10"},
        headers=outsider_risk,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_outsider_cannot_run_var_for_a_walled_book(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    admin = await auth_headers(UserRole.ADMIN, username="wall-admin-9")
    outsider_risk = await auth_headers(UserRole.RISK_MANAGER, username="wall-outsider-risk-9")
    _cp_id, book_id = await _seed_restricted_book(client, db_session, admin)

    resp = await client.post(
        "/api/v1/risk/var/run",
        json={"book_id": book_id, "as_of_date": "2026-01-10", "confidence_level": 95},
        headers=outsider_risk,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_portfolio_wide_var_requires_admin(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """book_id=None (portfolio-wide, across every book) is ADMIN-only -- there's no
    single book to check membership against, and silently narrowing it to "just the
    caller's accessible books" would be a different number under the same label."""
    risk = await auth_headers(UserRole.RISK_MANAGER, username="wall-portfolio-risk")

    resp = await client.post(
        "/api/v1/risk/var/run",
        json={"as_of_date": "2026-01-10", "confidence_level": 95},
        headers=risk,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_outsider_cannot_create_a_limit_for_a_walled_book(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    admin = await auth_headers(UserRole.ADMIN, username="wall-admin-10")
    outsider_risk = await auth_headers(UserRole.RISK_MANAGER, username="wall-outsider-risk-10")
    _cp_id, book_id = await _seed_restricted_book(client, db_session, admin)

    resp = await client.post(
        "/api/v1/limits",
        json={
            "book_id": book_id,
            "commodity": "HENRY_HUB",
            "limit_type": "VOLUME",
            "threshold": 100,
        },
        headers=outsider_risk,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_outsider_export_of_a_walled_book_is_forbidden_by_id_and_empty_unfiltered(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    admin = await auth_headers(UserRole.ADMIN, username="wall-admin-11")
    outsider = await auth_headers(UserRole.TRADER, username="wall-outsider-11")
    cp_id, book_id = await _seed_restricted_book(client, db_session, admin)
    create_resp = await client.post(
        "/api/v1/trades", json=_trade_payload(cp_id, book_id), headers=admin
    )
    trade_id = create_resp.json()["id"]

    # Explicitly asking for this book's export: 403.
    by_id = await client.get(
        "/api/v1/export/trades", params={"book_id": book_id, "format": "json"}, headers=outsider
    )
    assert by_id.status_code == 403

    # Unfiltered ("every trade I can see") export: the walled trade must not appear.
    unfiltered = await client.get(
        "/api/v1/export/trades", params={"format": "json"}, headers=outsider
    )
    assert unfiltered.status_code == 200
    assert trade_id not in [row["id"] for row in unfiltered.json()]


@pytest.mark.asyncio
async def test_revoking_membership_removes_access(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    admin = await auth_headers(UserRole.ADMIN, username="wall-admin-12")
    member = await auth_headers(UserRole.TRADER, username="wall-member-12")
    cp_id, book_id = await _seed_restricted_book(client, db_session, admin)
    member_id = await _user_id(db_session, "wall-member-12")
    await _grant(client, book_id, member_id, admin)

    first = await client.post("/api/v1/trades", json=_trade_payload(cp_id, book_id), headers=member)
    assert first.status_code == 201

    revoke_resp = await client.delete(f"/api/v1/books/{book_id}/members/{member_id}", headers=admin)
    assert revoke_resp.status_code == 204

    second = await client.post(
        "/api/v1/trades", json=_trade_payload(cp_id, book_id), headers=member
    )
    assert second.status_code == 403


@pytest.mark.asyncio
async def test_unassigning_the_desk_restores_unrestricted_access(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    admin = await auth_headers(UserRole.ADMIN, username="wall-admin-13")
    outsider = await auth_headers(UserRole.TRADER, username="wall-outsider-13")
    cp_id, book_id = await _seed_restricted_book(client, db_session, admin)

    blocked = await client.post(
        "/api/v1/trades", json=_trade_payload(cp_id, book_id), headers=outsider
    )
    assert blocked.status_code == 403

    unassign_resp = await client.put(
        f"/api/v1/books/{book_id}/desk", json={"desk_id": None}, headers=admin
    )
    assert unassign_resp.status_code == 204

    allowed = await client.post(
        "/api/v1/trades", json=_trade_payload(cp_id, book_id), headers=outsider
    )
    assert allowed.status_code == 201


@pytest.mark.asyncio
async def test_a_book_with_no_desk_is_unrestricted_for_any_trader(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """The default/legacy case: a book that was never assigned to a desk behaves
    exactly as it did before this module existed."""
    trader = await auth_headers(UserRole.TRADER, username="wall-unrestricted-trader")
    counterparty = Counterparty(name="Tau Open Trading")
    book = Book(name="Tau Open Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()

    resp = await client.post(
        "/api/v1/trades",
        json=_trade_payload(str(counterparty.id), str(book.id)),
        headers=trader,
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_entitlement_management_endpoints_are_admin_only(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    risk = await auth_headers(UserRole.RISK_MANAGER, username="wall-nonadmin-14")
    counterparty = Counterparty(name="Upsilon Trading")
    book = Book(name="Upsilon Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()

    assert (
        await client.post("/api/v1/desks", json={"name": "Should Fail Desk"}, headers=risk)
    ).status_code == 403
    assert (
        await client.put(f"/api/v1/books/{book.id}/desk", json={"desk_id": None}, headers=risk)
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/books/{book.id}/members",
            json={"user_id": str(book.id)},  # any well-formed uuid; request never gets that far
            headers=risk,
        )
    ).status_code == 403
