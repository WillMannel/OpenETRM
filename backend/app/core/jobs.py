"""Arq Redis pool + a thin polling-status wrapper.

The pool is created lazily and cached at module scope rather than tied to FastAPI's
lifespan, specifically so it stays a plain dependency (`Depends(get_arq_pool)`) that
tests can override with `app.dependency_overrides[get_arq_pool] = ...` -- routes that
never call it never need a live Redis, which is what keeps the fast SQLite-backed test
suite Redis-free. Same pool doubles as what enqueues jobs that app.tasks.worker's Arq
worker process picks up.
"""

from dataclasses import dataclass
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job, JobStatus

from app.core.config import get_settings

settings = get_settings()

_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _pool


@dataclass(frozen=True)
class JobSnapshot:
    job_id: str
    status: str
    result: Any | None


async def get_job_snapshot(pool: ArqRedis, job_id: str) -> JobSnapshot:
    job = Job(job_id, pool)
    status = await job.status()
    result = None
    if status == JobStatus.complete:
        info = await job.result_info()
        result = info.result if info is not None else None
    return JobSnapshot(job_id=job_id, status=status.value, result=result)
