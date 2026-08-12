import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_role
from app.common.enums import UserRole
from app.common.exceptions import ForbiddenError, NotFoundError, ValidationFailedError
from app.modules.auth.models import User
from app.modules.trade_capture.schemas import (
    AmendmentRequestCreate,
    BookCreate,
    BookRead,
    CancellationRequestCreate,
    CounterpartyCreate,
    CounterpartyRead,
    ReviewDecision,
    TradeChangeRequestRead,
    TradeCreate,
    TradeRead,
)
from app.modules.trade_capture.service import ReferenceDataService, TradeCaptureService

router = APIRouter(prefix="/trades", tags=["trade-capture"])
reference_data_router = APIRouter(tags=["reference-data"])
change_requests_router = APIRouter(prefix="/trade-change-requests", tags=["trade-capture"])

_TRADER_OR_ADMIN = require_role(UserRole.TRADER, UserRole.ADMIN)
_RISK_OR_ADMIN = require_role(UserRole.RISK_MANAGER, UserRole.ADMIN)


@reference_data_router.post("/counterparties", response_model=CounterpartyRead, status_code=201)
async def create_counterparty(
    payload: CounterpartyCreate,
    session: AsyncSession = Depends(get_db),
    _actor: User = Depends(_TRADER_OR_ADMIN),
) -> CounterpartyRead:
    service = ReferenceDataService(session)
    counterparty = await service.create_counterparty(payload)
    return CounterpartyRead.model_validate(counterparty)


@reference_data_router.get("/counterparties", response_model=list[CounterpartyRead])
async def list_counterparties(
    session: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)
) -> list[CounterpartyRead]:
    service = ReferenceDataService(session)
    return [CounterpartyRead.model_validate(c) for c in await service.list_counterparties()]


@reference_data_router.post("/books", response_model=BookRead, status_code=201)
async def create_book(
    payload: BookCreate,
    session: AsyncSession = Depends(get_db),
    _actor: User = Depends(_TRADER_OR_ADMIN),
) -> BookRead:
    service = ReferenceDataService(session)
    book = await service.create_book(payload)
    return BookRead.model_validate(book)


@reference_data_router.get("/books", response_model=list[BookRead])
async def list_books(
    session: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)
) -> list[BookRead]:
    service = ReferenceDataService(session)
    return [BookRead.model_validate(b) for b in await service.list_books()]


@router.post("", response_model=TradeRead, status_code=201)
async def create_trade(
    payload: TradeCreate,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_TRADER_OR_ADMIN),
) -> TradeRead:
    service = TradeCaptureService(session)
    try:
        trade = await service.create_trade(payload, actor)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return TradeRead.model_validate(trade)


@router.get("", response_model=list[TradeRead])
async def list_trades(
    book_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> list[TradeRead]:
    service = TradeCaptureService(session)
    try:
        trades = await service.list_trades(actor=actor, book_id=book_id, limit=limit, offset=offset)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return [TradeRead.model_validate(t) for t in trades]


@router.get("/{trade_id}", response_model=TradeRead)
async def get_trade(
    trade_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> TradeRead:
    service = TradeCaptureService(session)
    try:
        trade = await service.get_trade(trade_id, actor)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return TradeRead.model_validate(trade)


@router.post("/{trade_id}/confirm", response_model=TradeRead)
async def confirm_trade(
    trade_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_RISK_OR_ADMIN),
) -> TradeRead:
    service = TradeCaptureService(session)
    try:
        trade = await service.confirm_trade(trade_id, actor)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return TradeRead.model_validate(trade)


@router.post("/{trade_id}/amendments", response_model=TradeChangeRequestRead, status_code=201)
async def request_amendment(
    trade_id: uuid.UUID,
    payload: AmendmentRequestCreate,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_TRADER_OR_ADMIN),
) -> TradeChangeRequestRead:
    service = TradeCaptureService(session)
    try:
        change_request = await service.request_amendment(trade_id, payload, actor)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return TradeChangeRequestRead.model_validate(change_request)


@router.post("/{trade_id}/cancellations", response_model=TradeChangeRequestRead, status_code=201)
async def request_cancellation(
    trade_id: uuid.UUID,
    payload: CancellationRequestCreate,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_TRADER_OR_ADMIN),
) -> TradeChangeRequestRead:
    service = TradeCaptureService(session)
    try:
        change_request = await service.request_cancellation(trade_id, payload, actor)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return TradeChangeRequestRead.model_validate(change_request)


@change_requests_router.get("", response_model=list[TradeChangeRequestRead])
async def list_pending_change_requests(
    session: AsyncSession = Depends(get_db), actor: User = Depends(_RISK_OR_ADMIN)
) -> list[TradeChangeRequestRead]:
    service = TradeCaptureService(session)
    return [
        TradeChangeRequestRead.model_validate(c)
        for c in await service.list_pending_change_requests(actor)
    ]


@change_requests_router.get("/{change_request_id}", response_model=TradeChangeRequestRead)
async def get_change_request(
    change_request_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> TradeChangeRequestRead:
    service = TradeCaptureService(session)
    try:
        change_request = await service.get_change_request(change_request_id, actor)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return TradeChangeRequestRead.model_validate(change_request)


@change_requests_router.post("/{change_request_id}/approve", response_model=TradeChangeRequestRead)
async def approve_change_request(
    change_request_id: uuid.UUID,
    payload: ReviewDecision,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_RISK_OR_ADMIN),
) -> TradeChangeRequestRead:
    service = TradeCaptureService(session)
    try:
        change_request = await service.approve_change_request(
            change_request_id, actor, payload.note
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return TradeChangeRequestRead.model_validate(change_request)


@change_requests_router.post("/{change_request_id}/reject", response_model=TradeChangeRequestRead)
async def reject_change_request(
    change_request_id: uuid.UUID,
    payload: ReviewDecision,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_RISK_OR_ADMIN),
) -> TradeChangeRequestRead:
    service = TradeCaptureService(session)
    try:
        change_request = await service.reject_change_request(change_request_id, actor, payload.note)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return TradeChangeRequestRead.model_validate(change_request)
