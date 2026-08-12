import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_role
from app.common.enums import Commodity, UserRole
from app.common.exceptions import ForbiddenError, NotFoundError
from app.modules.auth.models import User
from app.modules.valuation.schemas import (
    BookPnlSummary,
    PositionRead,
    ValuationResultRead,
    ValuationRunCreate,
    ValuationRunRead,
    ValuationRunSummary,
)
from app.modules.valuation.service import ValuationService

router = APIRouter(prefix="/positions", tags=["valuation"])

_RISK_OR_ADMIN = require_role(UserRole.RISK_MANAGER, UserRole.ADMIN)


@router.get("/{book_id}/pnl", response_model=BookPnlSummary)
async def get_book_pnl(
    book_id: uuid.UUID,
    as_of_date: date,
    commodity: Commodity = Commodity.HENRY_HUB,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> BookPnlSummary:
    """Pure read: computes mark-to-market fresh from live trades/the published curve
    and returns it -- never writes a row, so calling this any number of times has no
    side effect (see ValuationService.mark_to_market / compute_mark_to_market). For a
    durable, reportable snapshot that BI tools and exports read, see
    POST /positions/{book_id}/valuation-runs."""
    service = ValuationService(session)
    try:
        positions, results = await service.mark_to_market(book_id, as_of_date, commodity, actor)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return BookPnlSummary(
        book_id=book_id,
        as_of_date=as_of_date,
        total_mtm_value=sum((r.mtm_value for r in results), Decimal(0)),
        total_unrealized_pnl=sum((r.unrealized_pnl for r in results), Decimal(0)),
        positions=[PositionRead.model_validate(p) for p in positions],
    )


@router.post("/{book_id}/valuation-runs", response_model=ValuationRunSummary, status_code=201)
async def create_valuation_run(
    book_id: uuid.UUID,
    payload: ValuationRunCreate,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_RISK_OR_ADMIN),
) -> ValuationRunSummary:
    """The deliberate write path: computes mark-to-market and persists it as a new
    ValuationRun with its Position/ValuationResult rows, for audit history and for
    reporting views/exports to read (they always read the latest run for a given
    book/commodity/as_of_date -- see v_positions_flat/v_valuation_results_flat).
    Role-gated the same as other risk/middle-office write actions (VaR runs, sensitivity
    runs): booking a trade doesn't require publishing an official valuation snapshot,
    but publishing one is a risk/middle-office action, not a trader self-service one."""
    service = ValuationService(session)
    try:
        run, computation = await service.persist_valuation_run(
            book_id, payload.as_of_date, payload.commodity, actor=actor
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return ValuationRunSummary(
        run=ValuationRunRead.model_validate(run),
        total_mtm_value=sum((r.mtm_value for r in computation.results), Decimal(0)),
        total_unrealized_pnl=sum((r.unrealized_pnl for r in computation.results), Decimal(0)),
        positions=[PositionRead.model_validate(p) for p in computation.positions],
        results=[ValuationResultRead.model_validate(r) for r in computation.results],
    )
