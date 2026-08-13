import builtins
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload

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

    async def get_book(self, book_id: uuid.UUID) -> Book | None:
        return await self._session.get(Book, book_id)


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
        self,
        *,
        book_id: uuid.UUID | None = None,
        book_ids: builtins.set[uuid.UUID] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Trade]:
        """`book_id` scopes to one book; `book_ids` scopes to a set (used to filter to
        a caller's entitled books when no single book_id was requested -- see
        EntitlementService.accessible_book_ids). Passing both is redundant but not a
        conflict: both clauses AND together, same as any other combination of filters
        on this query."""
        stmt = select(Trade).order_by(Trade.trade_date.desc()).limit(limit).offset(offset)
        if book_id is not None:
            stmt = stmt.where(Trade.book_id == book_id)
        if book_ids is not None:
            stmt = stmt.where(Trade.book_id.in_(book_ids))
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
        method named `list`, which otherwise shadows the builtin generic for mypy.)

        Overrides `Trade.counterparty`/`.book`'s model-level `lazy="joined"` with
        `lazyload` here specifically -- every *current* caller of this method
        (valuation's position-building, risk's trade fetches, trade_capture's
        pre-trade limit checks) only ever touches trade economics (volume, price,
        dates, buy_sell, commodity), never the counterparty's name or book's
        description, so skipping the eager join avoids its cost entirely for them.
        `lazyload` rather than `noload` deliberately: it still lazy-loads correctly
        (one query, on demand) if some future caller *does* touch `.counterparty`/
        `.book` on a Trade from this method, whereas `noload` would silently hand
        back `None` for a relationship whose FK is NOT NULL -- a wrong-data bug
        that's easy to introduce later and easy to miss in review, versus a lazy
        load that's merely a missed optimization. At realistic scale this join
        dominated wall-clock time far more than the query itself (task P1-9's
        benchmark: ~6ms for the bare query vs. ~1.2-1.4s once hydration was
        included, at 15,000 rows -- see PERFORMANCE.md and ARCHITECTURE.md's "Scale
        and performance"). `TradeRepository.list`/`.get` (the trade-blotter/
        detail-view methods, which DO need counterparty/book names for
        `TradeRead`) are unaffected -- this override is scoped to this one query."""
        stmt = (
            select(Trade)
            .where(Trade.status.in_([s.value for s in LIVE_TRADE_STATUSES]))
            .options(lazyload(Trade.counterparty), lazyload(Trade.book))
        )
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

    async def list_pending(
        self, book_ids: builtins.set[uuid.UUID] | None = None
    ) -> list[TradeChangeRequest]:
        """`book_ids=None` returns every pending request (ADMIN's unrestricted view);
        otherwise scoped to change requests on trades in one of those books -- a
        RISK_MANAGER on desk A must not see (or approve/reject) desk B's pending
        amendment/cancellation reasons. Joins to Trade only to filter; the result rows
        are still TradeChangeRequest objects."""
        stmt = select(TradeChangeRequest).where(
            TradeChangeRequest.status == ChangeRequestStatus.PENDING
        )
        if book_ids is not None:
            stmt = stmt.join(Trade, Trade.id == TradeChangeRequest.trade_id).where(
                Trade.book_id.in_(book_ids)
            )
        stmt = stmt.order_by(TradeChangeRequest.requested_at)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
