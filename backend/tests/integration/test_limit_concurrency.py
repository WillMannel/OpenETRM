"""Concurrency correctness of VOLUME limit enforcement (task #27, P0-5).

The bug this prevents: `TradeCaptureService._enforce_volume_limit_for_confirm` reads
the book's live trades, computes a prospective net volume including the trade being
confirmed, and checks it against the book's VOLUME limit -- classic check-then-act.
Two trades confirmed *concurrently* in the same book+commodity can each read the same
pre-confirm state, each individually compute a prospective volume within the limit,
and each pass its check -- even though their *combined* effect, once both are
CONFIRMED, breaches the limit. Neither confirm's check ever saw the other's change.

SQLite (the default test suite's backend) cannot demonstrate this at all: aiosqlite
serializes all access through one connection/thread, so there is no real concurrent
execution to race. This test needs a real Postgres with genuinely independent
connections, so it's gated behind RUN_POSTGRES_CONCURRENCY_TESTS=1 (set by
.github/workflows/ci.yml's backend-integration-postgres job) exactly like
test_worker_e2e.py's RUN_WORKER_E2E_TESTS gate, and for the same reason.

Both scenarios (the locking primitive in isolation, then the end-to-end confirm race)
live in one test function rather than two, deliberately -- see test_worker_e2e.py's
module docstring for why: app.core.db's engine/session factory is created once and
cached for the process's lifetime, but asyncpg connections are bound to the event loop
that opened them, and pytest-asyncio hands each test function a fresh loop by default.
Two test functions sharing that cached, loop-bound engine across that boundary fails
with "Future attached to a different loop" against real Postgres.
"""

import asyncio
import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_POSTGRES_CONCURRENCY_TESTS") != "1",
    reason="set RUN_POSTGRES_CONCURRENCY_TESTS=1 with a real DATABASE_URL to run this",
)


async def _provision_user(
    client: AsyncClient, role: str, password: str = "concurrency-pw-1"
) -> dict:
    from app.core.db import async_session_factory
    from app.modules.auth.repository import UserRepository

    username = f"conc-{uuid.uuid4().hex[:8]}"
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    assert register_resp.status_code == 201

    async with async_session_factory() as session:
        user = await UserRepository(session).get_by_username(username)
        user.role = role
        await session.commit()

    login_resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert login_resp.status_code == 200
    return {"Authorization": f"Bearer {login_resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_volume_limit_locking_closes_the_concurrent_confirm_race():
    from app.common.enums import Commodity
    from app.core.db import async_session_factory
    from app.main import app
    from app.modules.limits.models import BookLimit
    from app.modules.limits.service import LimitService
    from app.modules.trade_capture.models import Book, Counterparty

    # --- Part 1: the locking primitive in isolation --------------------------------
    # Session A locks the limit row and holds it; session B's lock attempt must
    # genuinely block until A commits, not return immediately. Proven with a
    # bounded wait -- if the lock didn't work, B would unblock well before A does.
    async with async_session_factory() as setup_session:
        lock_book = Book(name=f"Concurrency Lock Book {uuid.uuid4().hex[:8]}")
        setup_session.add(lock_book)
        await setup_session.commit()
        limit = BookLimit(
            book_id=lock_book.id,
            commodity=Commodity.HENRY_HUB.value,
            limit_type="VOLUME",
            threshold=1000,
        )
        setup_session.add(limit)
        await setup_session.commit()
        lock_book_id = lock_book.id

    session_a = async_session_factory()
    session_b = async_session_factory()
    try:
        locked_by_a = asyncio.Event()
        release_a = asyncio.Event()
        b_unblocked = asyncio.Event()

        async def hold_lock_in_a():
            await LimitService(session_a).lock_volume_limit(lock_book_id, Commodity.HENRY_HUB)
            locked_by_a.set()
            await release_a.wait()
            await session_a.commit()

        async def attempt_lock_in_b():
            await locked_by_a.wait()
            await LimitService(session_b).lock_volume_limit(lock_book_id, Commodity.HENRY_HUB)
            b_unblocked.set()

        task_a = asyncio.create_task(hold_lock_in_a())
        task_b = asyncio.create_task(attempt_lock_in_b())

        await locked_by_a.wait()
        await asyncio.sleep(0.3)
        assert not b_unblocked.is_set(), "B's lock attempt returned before A released it"

        release_a.set()
        await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=5.0)
        assert b_unblocked.is_set()
        await session_b.commit()
    finally:
        await session_a.close()
        await session_b.close()

    # --- Part 2: the end-to-end proof via two real concurrent confirm requests -----
    # Two trades (600 units each) in the same book+commodity, confirmed concurrently,
    # against a VOLUME limit of 1000. Neither trade alone breaches it (600 <= 1000);
    # confirmed together they would (1200 > 1000). Exactly one of the two concurrent
    # confirm requests must succeed and the other must be rejected as a limit breach
    # -- never both succeeding (the bug this fixes) and never both failing.
    async with async_session_factory() as session:
        counterparty = Counterparty(name=f"Concurrency Trading {uuid.uuid4().hex[:8]}")
        confirm_book = Book(name=f"Concurrency Confirm Book {uuid.uuid4().hex[:8]}")
        session.add_all([counterparty, confirm_book])
        await session.commit()
        cp_id, confirm_book_id = str(counterparty.id), str(confirm_book.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        trader = await _provision_user(client, "TRADER")
        risk = await _provision_user(client, "RISK_MANAGER")

        limit_resp = await client.post(
            "/api/v1/limits",
            json={
                "book_id": confirm_book_id,
                "commodity": "HENRY_HUB",
                "limit_type": "VOLUME",
                "threshold": 1000,
            },
            headers=risk,
        )
        assert limit_resp.status_code == 201

        trade_ids = []
        for _ in range(2):
            resp = await client.post(
                "/api/v1/trades",
                json={
                    "trade_date": "2026-01-10",
                    "counterparty_id": cp_id,
                    "book_id": confirm_book_id,
                    "trade_type": "SWAP",
                    "buy_sell": "BUY",
                    "volume": 600,
                    "fixed_price": 3.00,
                    "delivery_start_month": "2026-06-01",
                    "delivery_end_month": "2026-06-01",
                },
                headers=trader,
            )
            assert resp.status_code == 201
            trade_ids.append(resp.json()["id"])

        results = await asyncio.gather(
            *(
                client.post(f"/api/v1/trades/{trade_id}/confirm", headers=risk)
                for trade_id in trade_ids
            )
        )

        statuses = sorted(r.status_code for r in results)
        assert statuses == [200, 422], (
            f"expected exactly one confirm to succeed (200) and one to be rejected as "
            f"a limit breach (422), got {statuses} -- {[r.text for r in results]}"
        )

        breaches_resp = await client.get(
            "/api/v1/limits/breaches", params={"book_id": confirm_book_id}, headers=risk
        )
        assert breaches_resp.status_code == 200
        assert len(breaches_resp.json()) == 1
