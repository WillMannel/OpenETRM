import builtins
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import LIVE_TRADE_STATUSES, ChangeRequestStatus, Commodity
from app.modules.trade_capture.models import Book, Counterparty, Trade, TradeChangeRequest


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
        """Flushes, doesn't commit -- callers that also need to write an audit entry
        atomically alongside the trade (see TradeCaptureService) own the commit."""
        self._session.add(trade)
        await self._session.flush()
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

    async def list_live(
        self, book_id: uuid.UUID | None = None, commodity: Commodity | None = None
    ) -> builtins.list[Trade]:
        """Trades in a LIVE_TRADE_STATUSES status -- a draft (NEW), superseded
        (AMENDED), or CANCELLED trade must never count toward a position, a book's P&L,
        risk, or a pre-trade limit check. `book_id=None` returns every live trade
        across all books (used for whole-portfolio risk runs). `commodity=None`
        returns every commodity -- callers that feed the result into a single
        curve-valued number (a position, a VaR run, a limit check) MUST pass the
        commodity they're valuing against, or risk silently netting unrelated
        commodities together (see test_multi_commodity_book.py). The single shared
        query every one of those call sites goes through.
        (Return type is spelled `builtins.list` because this class also defines a
        method named `list`, which otherwise shadows the builtin generic for mypy.)"""
        stmt = select(Trade).where(Trade.status.in_([s.value for s in LIVE_TRADE_STATUSES]))
        if book_id is not None:
            stmt = stmt.where(Trade.book_id == book_id)
        if commodity is not None:
            stmt = stmt.where(Trade.commodity == commodity)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class TradeChangeRequestRepository:
    """No auto-commit here (unlike TradeRepository/ReferenceDataRepository) --
    lifecycle operations touch a change request, the trade(s) it targets, and an audit
    entry together, and TradeCaptureService owns committing that as one transaction."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, change_request: TradeChangeRequest) -> TradeChangeRequest:
        self._session.add(change_request)
        await self._session.flush()
        return change_request

    async def get(self, change_request_id: uuid.UUID) -> TradeChangeRequest | None:
        return await self._session.get(TradeChangeRequest, change_request_id)

    async def list_pending(self) -> list[TradeChangeRequest]:
        stmt = (
            select(TradeChangeRequest)
            .where(TradeChangeRequest.status == ChangeRequestStatus.PENDING)
            .order_by(TradeChangeRequest.requested_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
