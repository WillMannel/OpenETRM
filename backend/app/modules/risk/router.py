import uuid
from datetime import date

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_arq_pool, get_db
from app.common.enums import Commodity
from app.common.exceptions import NotFoundError
from app.common.job_schemas import JobEnqueuedRead, JobStatusRead
from app.core.jobs import get_job_snapshot
from app.modules.risk.models import VarResult
from app.modules.risk.schemas import (
    DeltaLadderRead,
    DeltaLadderRunRequest,
    SensitivityResultRead,
    VarResultRead,
    VarRunRequest,
)
from app.modules.risk.service import RiskService

router = APIRouter(prefix="/risk", tags=["risk"])


@router.post("/var/run", response_model=VarResultRead, status_code=201)
async def run_var(payload: VarRunRequest, session: AsyncSession = Depends(get_db)) -> VarResultRead:
    """Synchronous VaR run -- fine for v1's small position/history size. See
    /risk/var/run-async for the background-job version (app.tasks.risk_tasks.run_var_job)
    once scenario windows/position counts get large enough to matter."""
    service = RiskService(session)
    result = await service.run_var(
        payload.book_id,
        payload.as_of_date,
        payload.commodity,
        int(payload.confidence_level),
        payload.scenario_window_days,
    )
    return VarResultRead.model_validate(result)


@router.post("/var/run-async", response_model=JobEnqueuedRead, status_code=202)
async def run_var_async(
    payload: VarRunRequest, pool: ArqRedis = Depends(get_arq_pool)
) -> JobEnqueuedRead:
    job = await pool.enqueue_job(
        "run_var_job",
        str(payload.book_id) if payload.book_id else None,
        payload.as_of_date.isoformat(),
        payload.commodity.value,
        int(payload.confidence_level),
        payload.scenario_window_days,
    )
    if job is None:
        raise HTTPException(status_code=503, detail="Failed to enqueue VaR job")
    return JobEnqueuedRead(job_id=job.job_id)


@router.get("/var/run-async/{job_id}", response_model=JobStatusRead)
async def get_var_job(job_id: str, pool: ArqRedis = Depends(get_arq_pool)) -> JobStatusRead:
    snapshot = await get_job_snapshot(pool, job_id)
    return JobStatusRead(job_id=snapshot.job_id, status=snapshot.status, result=snapshot.result)


@router.get("/var/{var_result_id}", response_model=VarResultRead)
async def get_var_result(
    var_result_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> VarResultRead:
    result = await session.get(VarResult, var_result_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"VarResult not found: {var_result_id}")
    return VarResultRead.model_validate(result)


@router.get("/delta-ladder", response_model=DeltaLadderRead)
async def get_delta_ladder(
    book_id: uuid.UUID,
    as_of_date: date,
    commodity: Commodity = Commodity.HENRY_HUB,
    session: AsyncSession = Depends(get_db),
) -> DeltaLadderRead:
    """Synchronous delta-ladder run. See /risk/delta-ladder/run-async for the
    background-job version (app.tasks.risk_tasks.run_sensitivities_job)."""
    service = RiskService(session)
    try:
        curve_id, results = await service.run_delta_ladder(book_id, as_of_date, commodity)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return DeltaLadderRead(
        book_id=book_id,
        as_of_date=as_of_date,
        curve_id=curve_id,
        buckets=[SensitivityResultRead.model_validate(r) for r in results],
    )


@router.post("/delta-ladder/run-async", response_model=JobEnqueuedRead, status_code=202)
async def run_delta_ladder_async(
    payload: DeltaLadderRunRequest, pool: ArqRedis = Depends(get_arq_pool)
) -> JobEnqueuedRead:
    job = await pool.enqueue_job(
        "run_sensitivities_job",
        str(payload.book_id),
        payload.as_of_date.isoformat(),
        payload.commodity.value,
    )
    if job is None:
        raise HTTPException(status_code=503, detail="Failed to enqueue delta-ladder job")
    return JobEnqueuedRead(job_id=job.job_id)


@router.get("/delta-ladder/run-async/{job_id}", response_model=JobStatusRead)
async def get_delta_ladder_job(
    job_id: str, pool: ArqRedis = Depends(get_arq_pool)
) -> JobStatusRead:
    snapshot = await get_job_snapshot(pool, job_id)
    return JobStatusRead(job_id=snapshot.job_id, status=snapshot.status, result=snapshot.result)
