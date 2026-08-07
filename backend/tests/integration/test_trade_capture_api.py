import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.modules.trade_capture.models import Book, Counterparty
from tests.conftest import AuthHeadersFactory


@pytest.mark.asyncio
async def test_create_and_list_trade(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty = Counterparty(name="Acme Energy Trading")
    book = Book(name="NatGas Desk")
    db_session.add_all([counterparty, book])
    await db_session.commit()

    payload = {
        "trade_date": "2026-01-15",
        "counterparty_id": str(counterparty.id),
        "book_id": str(book.id),
        "trade_type": "SWAP",
        "buy_sell": "BUY",
        "volume": 10000,
        "fixed_price": 3.25,
        "delivery_start_month": "2026-06-01",
        "delivery_end_month": "2026-08-01",
    }

    trader_headers = await auth_headers(UserRole.TRADER)
    create_resp = await client.post("/api/v1/trades", json=payload, headers=trader_headers)
    assert create_resp.status_code == 201
    trade_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "NEW"

    viewer_headers = await auth_headers(UserRole.VIEWER)
    list_resp = await client.get(
        "/api/v1/trades", params={"book_id": str(book.id)}, headers=viewer_headers
    )
    assert list_resp.status_code == 200
    trades = list_resp.json()
    assert len(trades) == 1
    assert trades[0]["id"] == trade_id
    assert trades[0]["counterparty"]["name"] == "Acme Energy Trading"


@pytest.mark.asyncio
async def test_create_trade_requires_authentication(client: AsyncClient, db_session: AsyncSession):
    resp = await client.post("/api/v1/trades", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_trade_rejects_viewer_role(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    viewer_headers = await auth_headers(UserRole.VIEWER)
    resp = await client.post("/api/v1/trades", json={}, headers=viewer_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_trade_rejects_invalid_delivery_range(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    counterparty = Counterparty(name="Beta Gas Co")
    book = Book(name="Beta Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()

    payload = {
        "trade_date": "2026-01-15",
        "counterparty_id": str(counterparty.id),
        "book_id": str(book.id),
        "trade_type": "FORWARD",
        "buy_sell": "SELL",
        "volume": 5000,
        "fixed_price": 3.0,
        "delivery_start_month": "2026-08-01",
        "delivery_end_month": "2026-06-01",  # end before start -> invalid
    }

    trader_headers = await auth_headers(UserRole.TRADER)
    resp = await client.post("/api/v1/trades", json=payload, headers=trader_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_and_list_counterparties_and_books(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER)
    cp_resp = await client.post(
        "/api/v1/counterparties", json={"name": "Delta Energy"}, headers=trader_headers
    )
    assert cp_resp.status_code == 201

    book_resp = await client.post(
        "/api/v1/books", json={"name": "Delta Book"}, headers=trader_headers
    )
    assert book_resp.status_code == 201

    viewer_headers = await auth_headers(UserRole.VIEWER)
    cp_list = await client.get("/api/v1/counterparties", headers=viewer_headers)
    assert cp_list.status_code == 200
    assert any(c["name"] == "Delta Energy" for c in cp_list.json())

    book_list = await client.get("/api/v1/books", headers=viewer_headers)
    assert book_list.status_code == 200
    assert any(b["name"] == "Delta Book" for b in book_list.json())
