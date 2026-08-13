"""Regression coverage for a real bug found in a code audit: GET /positions/{book_id}/pnl
called `session.add()`/`commit()` on every request even though it's a read endpoint --
three identical GETs produced three duplicate Position/ValuationResult rows for the
same book/as_of_date snapshot (proven directly against the DB: booking one trade and
calling the endpoint three times left `positions` with 3 rows instead of 1).

The fix (task #25, P0-3) separates computation from persistence: GET now only computes
(no session writes at all), and a new POST /positions/{book_id}/valuation-runs is the
sole write path, creating an explicit ValuationRun each time it's called. These tests
pin both halves: the read endpoint must be safe to call any number of times, and the
write endpoint must produce exactly one run's worth of rows per call, distinguishable
by run_id across repeated calls.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.modules.trade_capture.models import Book, Counterparty
from app.modules.valuation.models import Position, ValuationResult, ValuationRun
from tests.conftest import AuthHeadersFactory


async def _seed_confirmed_trade(
    client: AsyncClient, db_session: AsyncSession, trader_headers: dict, risk_headers: dict
) -> str:
    counterparty = Counterparty(name="Omicron Idempotency Trading")
    book = Book(name="Omicron Book")
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

    await client.post(
        "/api/v1/market-data/quotes",
        json={"quote_date": "2026-01-10", "delivery_month": "2026-06-01", "price": 3.10},
        headers=trader_headers,
    )
    await client.post(
        "/api/v1/curves/build", json={"as_of_date": "2026-01-10"}, headers=trader_headers
    )

    return str(book.id)


async def _row_count(db_session: AsyncSession, model) -> int:
    result = await db_session.execute(select(func.count()).select_from(model))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_repeated_get_pnl_writes_nothing_to_the_database(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader = await auth_headers(UserRole.TRADER, username="idem-trader")
    risk = await auth_headers(UserRole.RISK_MANAGER, username="idem-risk")
    book_id = await _seed_confirmed_trade(client, db_session, trader, risk)

    for _ in range(3):
        resp = await client.get(
            f"/api/v1/positions/{book_id}/pnl",
            params={"as_of_date": "2026-01-10"},
            headers=trader,
        )
        assert resp.status_code == 200
        assert resp.json()["total_unrealized_pnl"] == pytest.approx(1000.0)

    # The core bug: three identical reads must leave zero rows behind, not three.
    assert await _row_count(db_session, Position) == 0
    assert await _row_count(db_session, ValuationResult) == 0
    assert await _row_count(db_session, ValuationRun) == 0


@pytest.mark.asyncio
async def test_valuation_run_endpoint_persists_exactly_one_runs_worth_of_rows(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader = await auth_headers(UserRole.TRADER, username="idem-run-trader")
    risk = await auth_headers(UserRole.RISK_MANAGER, username="idem-run-risk")
    book_id = await _seed_confirmed_trade(client, db_session, trader, risk)

    resp = await client.post(
        f"/api/v1/positions/{book_id}/valuation-runs",
        json={"as_of_date": "2026-01-10"},
        headers=risk,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["total_unrealized_pnl"] == pytest.approx(1000.0)
    run_id = body["run"]["id"]

    assert await _row_count(db_session, ValuationRun) == 1
    assert await _row_count(db_session, Position) == 1
    assert await _row_count(db_session, ValuationResult) == 1

    position = (await db_session.execute(select(Position))).scalar_one()
    assert str(position.run_id) == run_id


@pytest.mark.asyncio
async def test_repeated_valuation_runs_each_get_their_own_row_set_not_a_conflict(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """Re-running (e.g. after a late trade or a curve republish) must succeed, not hit
    a unique-constraint violation from the previous run's rows -- each run gets its own
    run_id, so the (run_id, book, commodity, delivery_month) grain never collides
    across runs even though the book/commodity/month is identical each time."""
    trader = await auth_headers(UserRole.TRADER, username="idem-rerun-trader")
    risk = await auth_headers(UserRole.RISK_MANAGER, username="idem-rerun-risk")
    book_id = await _seed_confirmed_trade(client, db_session, trader, risk)

    first = await client.post(
        f"/api/v1/positions/{book_id}/valuation-runs",
        json={"as_of_date": "2026-01-10"},
        headers=risk,
    )
    second = await client.post(
        f"/api/v1/positions/{book_id}/valuation-runs",
        json={"as_of_date": "2026-01-10"},
        headers=risk,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["run"]["id"] != second.json()["run"]["id"]

    assert await _row_count(db_session, ValuationRun) == 2
    assert await _row_count(db_session, Position) == 2
    assert await _row_count(db_session, ValuationResult) == 2


@pytest.mark.asyncio
async def test_valuation_run_requires_risk_or_admin_role(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    trader = await auth_headers(UserRole.TRADER, username="idem-rbac-trader")
    risk = await auth_headers(UserRole.RISK_MANAGER, username="idem-rbac-risk")
    book_id = await _seed_confirmed_trade(client, db_session, trader, risk)

    resp = await client.post(
        f"/api/v1/positions/{book_id}/valuation-runs",
        json={"as_of_date": "2026-01-10"},
        headers=trader,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_export_positions_returns_latest_run_only(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """Two valuation runs for the same book/commodity/as_of_date must export as one
    position, not two -- export/reporting always reads the latest run."""
    trader = await auth_headers(UserRole.TRADER, username="idem-export-trader")
    risk = await auth_headers(UserRole.RISK_MANAGER, username="idem-export-risk")
    book_id = await _seed_confirmed_trade(client, db_session, trader, risk)

    for _ in range(2):
        run_resp = await client.post(
            f"/api/v1/positions/{book_id}/valuation-runs",
            json={"as_of_date": "2026-01-10"},
            headers=risk,
        )
        assert run_resp.status_code == 201
    latest_run_id = run_resp.json()["run"]["id"]

    export_resp = await client.get(
        "/api/v1/export/positions",
        params={"as_of_date": "2026-01-10", "book_id": book_id, "format": "json"},
        headers=trader,
    )
    assert export_resp.status_code == 200
    rows = export_resp.json()
    assert len(rows) == 1
    assert rows[0]["run_id"] == latest_run_id
