import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.common.enums import Commodity
from app.common.exceptions import NotFoundError
from app.modules.valuation.schemas import BookPnlSummary, PositionRead
from app.modules.valuation.service import ValuationService

router = APIRouter(prefix="/positions", tags=["valuation"])


@router.get("/{book_id}/pnl", response_model=BookPnlSummary)
async def get_book_pnl(
    book_id: uuid.UUID,
    as_of_date: date,
    commodity: Commodity = Commodity.HENRY_HUB,
    session: AsyncSession = Depends(get_db),
) -> BookPnlSummary:
    service = ValuationService(session)
    try:
        positions, results = await service.mark_to_market(book_id, as_of_date, commodity)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return BookPnlSummary(
        book_id=book_id,
        as_of_date=as_of_date,
        total_mtm_value=sum(r.mtm_value for r in results),
        total_unrealized_pnl=sum(r.unrealized_pnl for r in results),
        positions=[PositionRead.model_validate(p) for p in positions],
    )
