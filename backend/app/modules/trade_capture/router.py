import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.common.exceptions import NotFoundError
from app.modules.trade_capture.schemas import (
    BookCreate,
    BookRead,
    CounterpartyCreate,
    CounterpartyRead,
    TradeCreate,
    TradeRead,
)
from app.modules.trade_capture.service import ReferenceDataService, TradeCaptureService

router = APIRouter(prefix="/trades", tags=["trade-capture"])
reference_data_router = APIRouter(tags=["reference-data"])


@reference_data_router.post("/counterparties", response_model=CounterpartyRead, status_code=201)
async def create_counterparty(
    payload: CounterpartyCreate, session: AsyncSession = Depends(get_db)
) -> CounterpartyRead:
    service = ReferenceDataService(session)
    counterparty = await service.create_counterparty(payload)
    return CounterpartyRead.model_validate(counterparty)


@reference_data_router.get("/counterparties", response_model=list[CounterpartyRead])
async def list_counterparties(session: AsyncSession = Depends(get_db)) -> list[CounterpartyRead]:
    service = ReferenceDataService(session)
    return [CounterpartyRead.model_validate(c) for c in await service.list_counterparties()]


@reference_data_router.post("/books", response_model=BookRead, status_code=201)
async def create_book(payload: BookCreate, session: AsyncSession = Depends(get_db)) -> BookRead:
    service = ReferenceDataService(session)
    book = await service.create_book(payload)
    return BookRead.model_validate(book)


@reference_data_router.get("/books", response_model=list[BookRead])
async def list_books(session: AsyncSession = Depends(get_db)) -> list[BookRead]:
    service = ReferenceDataService(session)
    return [BookRead.model_validate(b) for b in await service.list_books()]


@router.post("", response_model=TradeRead, status_code=201)
async def create_trade(payload: TradeCreate, session: AsyncSession = Depends(get_db)) -> TradeRead:
    service = TradeCaptureService(session)
    trade = await service.create_trade(payload)
    return TradeRead.model_validate(trade)


@router.get("", response_model=list[TradeRead])
async def list_trades(
    book_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_db),
) -> list[TradeRead]:
    service = TradeCaptureService(session)
    trades = await service.list_trades(book_id=book_id, limit=limit, offset=offset)
    return [TradeRead.model_validate(t) for t in trades]


@router.get("/{trade_id}", response_model=TradeRead)
async def get_trade(trade_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> TradeRead:
    service = TradeCaptureService(session)
    try:
        trade = await service.get_trade(trade_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TradeRead.model_validate(trade)
