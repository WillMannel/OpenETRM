import uuid

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_arq_pool, get_current_user, get_db, require_role
from app.common.enums import UserRole
from app.common.exceptions import InsufficientMarketDataError, NotFoundError, ValidationFailedError
from app.common.job_schemas import JobEnqueuedRead, JobStatusRead
from app.core.jobs import get_job_snapshot
from app.modules.auth.models import User
from app.modules.market_data.schemas import (
    CurveBuildRequest,
    ForwardCurveRead,
    MarketDataPointCreate,
    MarketDataPointRead,
)
from app.modules.market_data.service import MarketDataService

router = APIRouter(tags=["market-data"])

_TRADER_OR_ADMIN = require_role(UserRole.TRADER, UserRole.ADMIN)


@router.post("/market-data/quotes", response_model=MarketDataPointRead, status_code=201)
async def add_quote(
    payload: MarketDataPointCreate,
    session: AsyncSession = Depends(get_db),
    _actor: User = Depends(_TRADER_OR_ADMIN),
) -> MarketDataPointRead:
    service = MarketDataService(session)
    try:
        quote = await service.add_quote(payload)
    except ValidationFailedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return MarketDataPointRead.model_validate(quote)


@router.post("/curves/build", response_model=ForwardCurveRead, status_code=201)
async def build_curve(
    payload: CurveBuildRequest,
    session: AsyncSession = Depends(get_db),
    _actor: User = Depends(_TRADER_OR_ADMIN),
) -> ForwardCurveRead:
    """Synchronous curve build -- blocks until the bootstrap finishes. Fine for v1's
    single-commodity monthly curve (milliseconds of work); see /curves/build-async for
    the background-job version once curve builds get heavier."""
    service = MarketDataService(session)
    try:
        curve = await service.build_curve(payload.commodity, payload.as_of_date)
    except InsufficientMarketDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ForwardCurveRead.model_validate(curve)


@router.post("/curves/build-async", response_model=JobEnqueuedRead, status_code=202)
async def build_curve_async(
    payload: CurveBuildRequest,
    pool: ArqRedis = Depends(get_arq_pool),
    _actor: User = Depends(_TRADER_OR_ADMIN),
) -> JobEnqueuedRead:
    """Enqueues the same build onto the Arq worker (app.tasks.curve_tasks.calibrate_curve)
    and returns immediately with a job id -- poll /curves/build-async/{job_id}."""
    job = await pool.enqueue_job(
        "calibrate_curve", payload.commodity.value, payload.as_of_date.isoformat()
    )
    if job is None:
        raise HTTPException(status_code=503, detail="Failed to enqueue curve build job")
    return JobEnqueuedRead(job_id=job.job_id)


@router.get("/curves/build-async/{job_id}", response_model=JobStatusRead)
async def get_curve_build_job(
    job_id: str, pool: ArqRedis = Depends(get_arq_pool), _user: User = Depends(get_current_user)
) -> JobStatusRead:
    snapshot = await get_job_snapshot(pool, job_id)
    return JobStatusRead(job_id=snapshot.job_id, status=snapshot.status, result=snapshot.result)


@router.get("/curves/{curve_id}", response_model=ForwardCurveRead)
async def get_curve(
    curve_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ForwardCurveRead:
    service = MarketDataService(session)
    try:
        curve = await service.get_curve(curve_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ForwardCurveRead.model_validate(curve)
