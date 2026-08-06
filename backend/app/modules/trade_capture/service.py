import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import NotFoundError
from app.modules.trade_capture.models import Book, Counterparty, Trade
from app.modules.trade_capture.repository import ReferenceDataRepository, TradeRepository
from app.modules.trade_capture.schemas import BookCreate, CounterpartyCreate, TradeCreate


class ReferenceDataService:
    def __init__(self, session: AsyncSession):
        self._repo = ReferenceDataRepository(session)

    async def create_counterparty(self, payload: CounterpartyCreate) -> Counterparty:
        return await self._repo.add_counterparty(Counterparty(**payload.model_dump()))

    async def list_counterparties(self) -> list[Counterparty]:
        return await self._repo.list_counterparties()

    async def create_book(self, payload: BookCreate) -> Book:
        return await self._repo.add_book(Book(**payload.model_dump()))

    async def list_books(self) -> list[Book]:
        return await self._repo.list_books()


class TradeCaptureService:
    def __init__(self, session: AsyncSession):
        self._repo = TradeRepository(session)

    async def create_trade(self, payload: TradeCreate) -> Trade:
        # Domain-level checks beyond field validation (payload already range-checked itself).
        trade = Trade(**payload.model_dump())
        return await self._repo.add(trade)

    async def get_trade(self, trade_id: uuid.UUID) -> Trade:
        trade = await self._repo.get(trade_id)
        if trade is None:
            raise NotFoundError("Trade", trade_id)
        return trade

    async def list_trades(
        self, *, book_id: uuid.UUID | None = None, limit: int = 100, offset: int = 0
    ) -> list[Trade]:
        return await self._repo.list(book_id=book_id, limit=limit, offset=offset)
