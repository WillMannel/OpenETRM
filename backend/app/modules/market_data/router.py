import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.common.exceptions import InsufficientMarketDataError, NotFoundError
from app.modules.market_data.schemas import (
    CurveBuildRequest,
    ForwardCurveRead,
    MarketDataPointCreate,
    MarketDataPointRead,
)
from app.modules.market_data.service import MarketDataService

router = APIRouter(tags=["market-data"])


@router.post("/market-data/quotes", response_model=MarketDataPointRead, status_code=201)
async def add_quote(
    payload: MarketDataPointCreate, session: AsyncSession = Depends(get_db)
) -> MarketDataPointRead:
    service = MarketDataService(session)
    quote = await service.add_quote(payload)
    return MarketDataPointRead.model_validate(quote)


@router.post("/curves/build", response_model=ForwardCurveRead, status_code=201)
async def build_curve(
    payload: CurveBuildRequest, session: AsyncSession = Depends(get_db)
) -> ForwardCurveRead:
    """Synchronous curve build. See app.tasks.curve_tasks for the async/Arq job version
    used once curve builds are wired into the background-job flow (build step 6)."""
    service = MarketDataService(session)
    try:
        curve = await service.build_curve(payload.commodity, payload.as_of_date)
    except InsufficientMarketDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ForwardCurveRead.model_validate(curve)


@router.get("/curves/{curve_id}", response_model=ForwardCurveRead)
async def get_curve(
    curve_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> ForwardCurveRead:
    service = MarketDataService(session)
    try:
        curve = await service.get_curve(curve_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ForwardCurveRead.model_validate(curve)
