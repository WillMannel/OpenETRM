import uuid
from datetime import date

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_arq_pool, get_current_user, get_db, require_role
from app.common.enums import Commodity, UserRole
from app.common.exceptions import ForbiddenError, NotFoundError
from app.common.job_schemas import JobEnqueuedRead, JobStatusRead
from app.core.jobs import get_job_snapshot
from app.modules.auth.models import User
from app.modules.risk.schemas import (
    DeltaLadderRead,
    DeltaLadderRunRequest,
    OptionGreeksRead,
    OptionGreeksRequest,
    OptionGreeksResponse,
    PnlAttributionRequest,
    PnlAttributionResponse,
    SensitivityResultRead,
    StressResultRead,
    StressTestRequest,
    StressTestResponse,
    VarResultRead,
    VarRunRequest,
)
from app.modules.risk.service import RiskService
from app.modules.risk.var.stress import StressScenario

router = APIRouter(prefix="/risk", tags=["risk"])

_RISK_OR_ADMIN = require_role(UserRole.RISK_MANAGER, UserRole.ADMIN)


@router.post("/var/run", response_model=VarResultRead, status_code=201)
async def run_var(
    payload: VarRunRequest,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_RISK_OR_ADMIN),
) -> VarResultRead:
    """Synchronous VaR run -- fine at v1's data volumes. See /risk/var/run-async for the
    background-job version (app.tasks.risk_tasks.run_var_job)."""
    service = RiskService(session)
    try:
        result = await service.run_var(
            payload.book_id,
            payload.as_of_date,
            payload.commodity,
            int(payload.confidence_level),
            payload.scenario_window_days,
            payload.method,
            actor=actor,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return VarResultRead.model_validate(result)


@router.post("/var/run-async", response_model=JobEnqueuedRead, status_code=202)
async def run_var_async(
    payload: VarRunRequest,
    pool: ArqRedis = Depends(get_arq_pool),
    actor: User = Depends(_RISK_OR_ADMIN),
) -> JobEnqueuedRead:
    job = await pool.enqueue_job(
        "run_var_job",
        str(payload.book_id) if payload.book_id else None,
        payload.as_of_date.isoformat(),
        payload.commodity.value,
        int(payload.confidence_level),
        payload.scenario_window_days,
        str(actor.id),
    )
    if job is None:
        raise HTTPException(status_code=503, detail="Failed to enqueue VaR job")
    return JobEnqueuedRead(job_id=job.job_id)


@router.get("/var/run-async/{job_id}", response_model=JobStatusRead)
async def get_var_job(
    job_id: str, pool: ArqRedis = Depends(get_arq_pool), _user: User = Depends(get_current_user)
) -> JobStatusRead:
    snapshot = await get_job_snapshot(pool, job_id)
    return JobStatusRead(job_id=snapshot.job_id, status=snapshot.status, result=snapshot.result)


@router.get("/var/{var_result_id}", response_model=VarResultRead)
async def get_var_result(
    var_result_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> VarResultRead:
    service = RiskService(session)
    try:
        result = await service.get_var_result(var_result_id, actor=actor)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return VarResultRead.model_validate(result)


@router.get("/delta-ladder", response_model=DeltaLadderRead)
async def get_delta_ladder(
    book_id: uuid.UUID,
    as_of_date: date,
    commodity: Commodity = Commodity.HENRY_HUB,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_RISK_OR_ADMIN),
) -> DeltaLadderRead:
    """Synchronous delta-ladder run. See /risk/delta-ladder/run-async for the
    background-job version (app.tasks.risk_tasks.run_sensitivities_job)."""
    service = RiskService(session)
    try:
        curve_id, results = await service.run_delta_ladder(
            book_id, as_of_date, commodity, actor=actor
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return DeltaLadderRead(
        book_id=book_id,
        as_of_date=as_of_date,
        curve_id=curve_id,
        buckets=[SensitivityResultRead.model_validate(r) for r in results],
    )


@router.post("/delta-ladder/run-async", response_model=JobEnqueuedRead, status_code=202)
async def run_delta_ladder_async(
    payload: DeltaLadderRunRequest,
    pool: ArqRedis = Depends(get_arq_pool),
    actor: User = Depends(_RISK_OR_ADMIN),
) -> JobEnqueuedRead:
    job = await pool.enqueue_job(
        "run_sensitivities_job",
        str(payload.book_id),
        payload.as_of_date.isoformat(),
        payload.commodity.value,
        str(actor.id),
    )
    if job is None:
        raise HTTPException(status_code=503, detail="Failed to enqueue delta-ladder job")
    return JobEnqueuedRead(job_id=job.job_id)


@router.get("/delta-ladder/run-async/{job_id}", response_model=JobStatusRead)
async def get_delta_ladder_job(
    job_id: str, pool: ArqRedis = Depends(get_arq_pool), _user: User = Depends(get_current_user)
) -> JobStatusRead:
    snapshot = await get_job_snapshot(pool, job_id)
    return JobStatusRead(job_id=snapshot.job_id, status=snapshot.status, result=snapshot.result)


@router.post("/stress-test", response_model=StressTestResponse)
async def run_stress_test(
    payload: StressTestRequest,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_RISK_OR_ADMIN),
) -> StressTestResponse:
    service = RiskService(session)
    scenarios = (
        [
            StressScenario(name=s.name, shock_type=s.shock_type, shock_value=s.shock_value)
            for s in payload.scenarios
        ]
        if payload.scenarios is not None
        else None
    )
    try:
        results = await service.run_stress_test(
            payload.book_id, payload.as_of_date, payload.commodity, scenarios, actor=actor
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return StressTestResponse(
        book_id=payload.book_id,
        as_of_date=payload.as_of_date,
        results=[StressResultRead.model_validate(r) for r in results],
    )


@router.get("/stress/{stress_result_id}", response_model=StressResultRead)
async def get_stress_result(
    stress_result_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> StressResultRead:
    service = RiskService(session)
    try:
        result = await service.get_stress_result(stress_result_id, actor=actor)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return StressResultRead.model_validate(result)


@router.post("/pnl-attribution", response_model=PnlAttributionResponse)
async def run_pnl_attribution(
    payload: PnlAttributionRequest,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_RISK_OR_ADMIN),
) -> PnlAttributionResponse:
    service = RiskService(session)
    try:
        attribution = await service.compute_pnl_attribution(
            payload.book_id,
            payload.prior_date,
            payload.current_date,
            payload.commodity,
            actor=actor,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return PnlAttributionResponse(
        book_id=payload.book_id,
        prior_date=payload.prior_date,
        current_date=payload.current_date,
        price_effect=attribution.price_effect,
        new_trade_effect=attribution.new_trade_effect,
        total=attribution.total,
    )


@router.post("/options/greeks", response_model=OptionGreeksResponse)
async def run_option_greeks(
    payload: OptionGreeksRequest,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_RISK_OR_ADMIN),
) -> OptionGreeksResponse:
    service = RiskService(session)
    try:
        results = await service.compute_option_greeks(
            payload.book_id, payload.as_of_date, payload.commodity, actor=actor
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return OptionGreeksResponse(
        book_id=payload.book_id,
        as_of_date=payload.as_of_date,
        results=[OptionGreeksRead.model_validate(r) for r in results],
    )


@router.get("/options/greeks/{result_id}", response_model=OptionGreeksRead)
async def get_option_greeks_result(
    result_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> OptionGreeksRead:
    service = RiskService(session)
    try:
        result = await service.get_option_greeks_result(result_id, actor=actor)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return OptionGreeksRead.model_validate(result)
