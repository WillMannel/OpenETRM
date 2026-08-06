import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.trade_capture.models import Book, Counterparty


@pytest.mark.asyncio
async def test_create_and_list_trade(client: AsyncClient, db_session: AsyncSession):
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

    create_resp = await client.post("/api/v1/trades", json=payload)
    assert create_resp.status_code == 201
    trade_id = create_resp.json()["id"]

    list_resp = await client.get("/api/v1/trades", params={"book_id": str(book.id)})
    assert list_resp.status_code == 200
    trades = list_resp.json()
    assert len(trades) == 1
    assert trades[0]["id"] == trade_id
    assert trades[0]["counterparty"]["name"] == "Acme Energy Trading"


@pytest.mark.asyncio
async def test_create_trade_rejects_invalid_delivery_range(
    client: AsyncClient, db_session: AsyncSession
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

    resp = await client.post("/api/v1/trades", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_and_list_counterparties_and_books(
    client: AsyncClient, db_session: AsyncSession
):
    cp_resp = await client.post("/api/v1/counterparties", json={"name": "Delta Energy"})
    assert cp_resp.status_code == 201

    book_resp = await client.post("/api/v1/books", json={"name": "Delta Book"})
    assert book_resp.status_code == 201

    cp_list = await client.get("/api/v1/counterparties")
    assert cp_list.status_code == 200
    assert any(c["name"] == "Delta Energy" for c in cp_list.json())

    book_list = await client.get("/api/v1/books")
    assert book_list.status_code == 200
    assert any(b["name"] == "Delta Book" for b in book_list.json())
