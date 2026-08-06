import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.common.enums import Commodity
from app.common.exceptions import NotFoundError
from app.modules.risk.models import VarResult
from app.modules.risk.schemas import (
    DeltaLadderRead,
    SensitivityResultRead,
    VarResultRead,
    VarRunRequest,
)
from app.modules.risk.service import RiskService

router = APIRouter(prefix="/risk", tags=["risk"])


@router.post("/var/run", response_model=VarResultRead, status_code=201)
async def run_var(payload: VarRunRequest, session: AsyncSession = Depends(get_db)) -> VarResultRead:
    """Synchronous VaR run. See app.tasks.risk_tasks for the Arq background-job version."""
    service = RiskService(session)
    result = await service.run_var(
        payload.book_id,
        payload.as_of_date,
        payload.commodity,
        int(payload.confidence_level),
        payload.scenario_window_days,
    )
    return VarResultRead.model_validate(result)


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
