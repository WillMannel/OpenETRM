"""Enqueue-side tests for the async (Arq-backed) endpoints, run against a fake pool so
they don't need a live Redis -- that's what keeps the default `pytest` run fast and
dependency-free. The actual worker execution path (job runs, result comes back through
Job.status()/result_info() against real Redis) is exercised by the Postgres+Redis CI job
(see .github/workflows/ci.yml's backend-integration-postgres job and
tests/integration/test_worker_e2e.py), not here.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_arq_pool
from app.common.enums import UserRole
from app.main import app
from app.modules.trade_capture.models import Book, Counterparty
from tests.conftest import AuthHeadersFactory


@dataclass
class _FakeJob:
    job_id: str


@dataclass
class _FakeArqPool:
    """Records every enqueue_job call so tests can assert on function name + args."""

    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    async def enqueue_job(self, function: str, *args: Any, **_kwargs: Any) -> _FakeJob:
        self.calls.append((function, args))
        return _FakeJob(job_id=f"fake-job-{len(self.calls)}")


@pytest.fixture
def fake_arq_pool():
    pool = _FakeArqPool()
    app.dependency_overrides[get_arq_pool] = lambda: pool
    yield pool
    del app.dependency_overrides[get_arq_pool]


async def _seed_book_and_counterparty(db_session: AsyncSession) -> tuple[str, str]:
    counterparty = Counterparty(name="Epsilon Trading")
    book = Book(name="Epsilon Book")
    db_session.add_all([counterparty, book])
    await db_session.commit()
    return str(counterparty.id), str(book.id)


@pytest.mark.asyncio
async def test_build_curve_async_enqueues_calibrate_curve_job(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_arq_pool: _FakeArqPool,
    auth_headers: AuthHeadersFactory,
):
    headers = await auth_headers(UserRole.TRADER)
    resp = await client.post(
        "/api/v1/curves/build-async", json={"as_of_date": "2026-01-10"}, headers=headers
    )

    assert resp.status_code == 202
    assert resp.json()["job_id"] == "fake-job-1"
    assert fake_arq_pool.calls == [("calibrate_curve", ("HENRY_HUB", "2026-01-10"))]


@pytest.mark.asyncio
async def test_run_var_async_enqueues_run_var_job(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_arq_pool: _FakeArqPool,
    auth_headers: AuthHeadersFactory,
):
    _, book_id = await _seed_book_and_counterparty(db_session)
    headers = await auth_headers(UserRole.RISK_MANAGER)

    resp = await client.post(
        "/api/v1/risk/var/run-async",
        json={"book_id": book_id, "as_of_date": "2026-01-10", "confidence_level": 99},
        headers=headers,
    )

    assert resp.status_code == 202
    assert resp.json()["job_id"] == "fake-job-1"
    assert fake_arq_pool.calls == [
        ("run_var_job", (book_id, "2026-01-10", "HENRY_HUB", 99, 250)),
    ]


@pytest.mark.asyncio
async def test_run_var_async_with_no_book_passes_none(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_arq_pool: _FakeArqPool,
    auth_headers: AuthHeadersFactory,
):
    headers = await auth_headers(UserRole.RISK_MANAGER)
    resp = await client.post(
        "/api/v1/risk/var/run-async", json={"as_of_date": "2026-01-10"}, headers=headers
    )

    assert resp.status_code == 202
    assert fake_arq_pool.calls[0][1][0] is None


@pytest.mark.asyncio
async def test_run_delta_ladder_async_enqueues_sensitivities_job(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_arq_pool: _FakeArqPool,
    auth_headers: AuthHeadersFactory,
):
    _, book_id = await _seed_book_and_counterparty(db_session)
    headers = await auth_headers(UserRole.RISK_MANAGER)

    resp = await client.post(
        "/api/v1/risk/delta-ladder/run-async",
        json={"book_id": book_id, "as_of_date": "2026-01-10"},
        headers=headers,
    )

    assert resp.status_code == 202
    assert fake_arq_pool.calls == [
        ("run_sensitivities_job", (book_id, "2026-01-10", "HENRY_HUB")),
    ]
