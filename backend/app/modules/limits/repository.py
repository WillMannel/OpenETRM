import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import Commodity, LimitBreachStatus, LimitType
from app.modules.limits.models import BookLimit, LimitBreach


class LimitRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, limit: BookLimit) -> BookLimit:
        self._session.add(limit)
        await self._session.commit()
        await self._session.refresh(limit)
        return limit

    async def get(self, limit_id: uuid.UUID) -> BookLimit | None:
        return await self._session.get(BookLimit, limit_id)

    async def get_by_book_and_type(
        self, book_id: uuid.UUID, commodity: Commodity, limit_type: LimitType
    ) -> BookLimit | None:
        stmt = select(BookLimit).where(
            BookLimit.book_id == book_id,
            BookLimit.commodity == commodity.value,
            BookLimit.limit_type == limit_type.value,
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_for_book(
        self, book_id: uuid.UUID | None = None, book_ids: set[uuid.UUID] | None = None
    ) -> list[BookLimit]:
        stmt = select(BookLimit).order_by(BookLimit.created_at)
        if book_id is not None:
            stmt = stmt.where(BookLimit.book_id == book_id)
        if book_ids is not None:
            stmt = stmt.where(BookLimit.book_id.in_(book_ids))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class LimitBreachRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, breach: LimitBreach) -> LimitBreach:
        """Flushes, doesn't commit -- callers combine this with an audit entry in one
        transaction, same pattern as TradeCaptureService."""
        self._session.add(breach)
        await self._session.flush()
        return breach

    async def get(self, breach_id: uuid.UUID) -> LimitBreach | None:
        return await self._session.get(LimitBreach, breach_id)

    async def list_open(
        self, book_id: uuid.UUID | None = None, book_ids: set[uuid.UUID] | None = None
    ) -> list[LimitBreach]:
        stmt = (
            select(LimitBreach)
            .where(LimitBreach.status == LimitBreachStatus.OPEN)
            .order_by(LimitBreach.occurred_at.desc())
        )
        if book_id is not None:
            stmt = stmt.where(LimitBreach.book_id == book_id)
        if book_ids is not None:
            stmt = stmt.where(LimitBreach.book_id.in_(book_ids))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
