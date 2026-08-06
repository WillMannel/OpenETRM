"""True end-to-end test of the async job path: a real Arq worker subprocess, talking to
a real Redis, actually executing app.tasks.curve_tasks/risk_tasks against the real
database the API itself is configured against (app.core.db.async_session_factory,
unmocked -- unlike tests/integration/test_async_jobs.py, this file does not override
get_db or get_arq_pool).

Deliberately skipped unless RUN_WORKER_E2E_TESTS=1 is set. This is not part of the
default `pytest` run: it needs the process's DATABASE_URL/REDIS_URL env vars (read once,
at import time, by app.core.db/app.core.jobs) to already point at real, migrated,
reachable services *before* pytest starts -- the SQLite-per-test trick the rest of the
suite uses doesn't apply here. See .github/workflows/ci.yml's backend-integration-postgres
job for how those env vars get set in CI (real Postgres/Timescale + Redis service
containers, `alembic upgrade head` run first). For local reproduction against SQLite +
a local `redis-server` instead of Postgres, see that CI job's comments for the
equivalent manual steps.

Both scenarios (curve build, VaR run) live in one test function rather than two,
deliberately: app.core.jobs' Arq pool and app.core.db's SQLAlchemy engine are each
created once and cached for the process's lifetime -- correct for a real app (one
event loop, forever), but asyncpg's connections are bound to the event loop that opened
them, and pytest-asyncio hands each *test function* a fresh event loop by default. Two
separate test functions reusing those same cached, loop-bound resources across that
boundary fails with "Future attached to a different loop" against real Postgres (it
happened to work against SQLite locally, which is laxer about this -- don't trust that).
One test function means one event loop for the whole scenario, which is both the fix
and the more honest shape for a test of one continuously-running process serving
multiple requests.
"""

import asyncio
import os
import subprocess
import sys
import time
import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_WORKER_E2E_TESTS") != "1",
    reason="set RUN_WORKER_E2E_TESTS=1 with real DATABASE_URL/REDIS_URL to run this",
)


@pytest.fixture
def worker_process():
    proc = subprocess.Popen(
        [sys.executable, "-m", "arq", "app.tasks.worker.WorkerSettings"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


async def _poll_until_complete(
    client: AsyncClient, status_url: str, timeout_s: float = 15.0
) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = await client.get(status_url)
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] == "complete":
            return body
        if body["status"] == "not_found":
            pytest.fail(f"job at {status_url} reported not_found -- worker likely isn't running")
        await asyncio.sleep(0.25)
    pytest.fail(f"job at {status_url} did not complete within {timeout_s}s")


@pytest.mark.asyncio
async def test_curve_build_and_var_run_async_on_real_worker(worker_process):
    from app.core.db import async_session_factory
    from app.main import app
    from app.modules.trade_capture.models import Book, Counterparty

    async with async_session_factory() as session:
        counterparty = Counterparty(name=f"E2E Counterparty {uuid.uuid4().hex[:8]}")
        book = Book(name=f"E2E Book {uuid.uuid4().hex[:8]}")
        session.add_all([counterparty, book])
        await session.commit()
        book_id = str(book.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # --- curve build: enqueue, poll, verify the worker actually built it ---
        curve_as_of = date(2026, 3, 10).isoformat()
        for delivery_month, price in [("2026-06-01", 3.1), ("2026-07-01", 3.2)]:
            resp = await client.post(
                "/api/v1/market-data/quotes",
                json={"quote_date": curve_as_of, "delivery_month": delivery_month, "price": price},
            )
            assert resp.status_code == 201

        curve_enqueue = await client.post(
            "/api/v1/curves/build-async", json={"as_of_date": curve_as_of}
        )
        assert curve_enqueue.status_code == 202
        curve_job_status = await _poll_until_complete(
            client, f"/api/v1/curves/build-async/{curve_enqueue.json()['job_id']}"
        )
        curve_id = curve_job_status["result"]
        assert curve_id is not None

        curve_resp = await client.get(f"/api/v1/curves/{curve_id}")
        assert curve_resp.status_code == 200
        assert len(curve_resp.json()["points"]) == 2

        # --- VaR run: enqueue, poll, verify the worker actually computed it ---
        var_as_of = date(2026, 3, 11).isoformat()
        for quote_date, price in [("2026-03-09", 3.0), ("2026-03-10", 3.1), (var_as_of, 3.05)]:
            resp = await client.post(
                "/api/v1/market-data/quotes",
                json={"quote_date": quote_date, "delivery_month": "2026-06-01", "price": price},
            )
            assert resp.status_code == 201

        var_enqueue = await client.post(
            "/api/v1/risk/var/run-async",
            json={"book_id": book_id, "as_of_date": var_as_of, "scenario_window_days": 30},
        )
        assert var_enqueue.status_code == 202
        var_job_status = await _poll_until_complete(
            client, f"/api/v1/risk/var/run-async/{var_enqueue.json()['job_id']}"
        )
        var_result_id = var_job_status["result"]
        assert var_result_id is not None

        var_resp = await client.get(f"/api/v1/risk/var/{var_result_id}")
        assert var_resp.status_code == 200
        assert var_resp.json()["var_value"] >= 0.0
