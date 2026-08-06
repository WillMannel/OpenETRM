import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.trade_capture.models import Book, Counterparty, Trade


class ReferenceDataRepository:
    """Counterparties and books: simple reference lists, not part of the trade
    lifecycle itself, so kept out of TradeRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add_counterparty(self, counterparty: Counterparty) -> Counterparty:
        self._session.add(counterparty)
        await self._session.commit()
        await self._session.refresh(counterparty)
        return counterparty

    async def list_counterparties(self) -> list[Counterparty]:
        result = await self._session.execute(select(Counterparty).order_by(Counterparty.name))
        return list(result.scalars().all())

    async def add_book(self, book: Book) -> Book:
        self._session.add(book)
        await self._session.commit()
        await self._session.refresh(book)
        return book

    async def list_books(self) -> list[Book]:
        result = await self._session.execute(select(Book).order_by(Book.name))
        return list(result.scalars().all())


class TradeRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, trade: Trade) -> Trade:
        self._session.add(trade)
        await self._session.commit()
        await self._session.refresh(trade, attribute_names=["counterparty", "book"])
        return trade

    async def get(self, trade_id: uuid.UUID) -> Trade | None:
        return await self._session.get(Trade, trade_id)

    async def list(
        self, *, book_id: uuid.UUID | None = None, limit: int = 100, offset: int = 0
    ) -> list[Trade]:
        stmt = select(Trade).order_by(Trade.trade_date.desc()).limit(limit).offset(offset)
        if book_id is not None:
            stmt = stmt.where(Trade.book_id == book_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
