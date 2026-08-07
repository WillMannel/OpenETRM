"""Trade capture + lifecycle: create, confirm, and the four-eyes amend/cancel flow.

State machine: NEW -[confirm]-> CONFIRMED -[request amendment]-> PENDING_AMENDMENT
-[approve]-> (this row becomes AMENDED, a new CONFIRMED row is created with the changes
applied and version+1) or -[reject]-> back to CONFIRMED. CONFIRMED
-[request cancellation]-> PENDING_CANCELLATION -[approve]-> CANCELLED or
-[reject]-> back to CONFIRMED.

Every transition writes an audit_log entry (app.modules.audit) in the same transaction
as the change itself, so the two can never disagree. Approval enforces four-eyes: the
approver must not be the user who made the request.
"""

import uuid
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import (
    AuditAction,
    BuySell,
    ChangeRequestStatus,
    ChangeRequestType,
    Currency,
    TradeStatus,
    TradeType,
    VolumeUnit,
)
from app.common.exceptions import NotFoundError, ValidationFailedError
from app.modules.audit.service import record_audit_event
from app.modules.auth.models import User
from app.modules.trade_capture.models import Book, Counterparty, Trade, TradeChangeRequest
from app.modules.trade_capture.repository import (
    ReferenceDataRepository,
    TradeChangeRequestRepository,
    TradeRepository,
)
from app.modules.trade_capture.schemas import (
    AmendmentRequestCreate,
    BookCreate,
    CancellationRequestCreate,
    CounterpartyCreate,
    TradeCreate,
)


def _enum_value(v: Any) -> Any:
    """ORM attributes on these str-mixin-enum columns come back as a plain `str` after
    a DB round trip, but as the actual enum instance on a freshly-constructed object --
    handle both uniformly."""
    return v.value if hasattr(v, "value") else v


def _trade_snapshot(trade: Trade) -> dict[str, Any]:
    """A JSON-safe dict of a trade's economic terms + status, for audit before/after."""
    return {
        "id": str(trade.id),
        "trade_date": trade.trade_date.isoformat(),
        "counterparty_id": str(trade.counterparty_id),
        "book_id": str(trade.book_id),
        "commodity": _enum_value(trade.commodity),
        "trade_type": _enum_value(trade.trade_type),
        "buy_sell": _enum_value(trade.buy_sell),
        "volume": float(trade.volume),
        "volume_unit": _enum_value(trade.volume_unit),
        "fixed_price": float(trade.fixed_price),
        "price_currency": _enum_value(trade.price_currency),
        "delivery_start_month": trade.delivery_start_month.isoformat(),
        "delivery_end_month": trade.delivery_end_month.isoformat(),
        "floating_index": trade.floating_index,
        "status": _enum_value(trade.status),
        "version": trade.version,
    }


_FIELD_COERCERS: dict[str, Callable[[Any], Any]] = {
    "trade_type": TradeType,
    "buy_sell": BuySell,
    "volume": float,
    "volume_unit": VolumeUnit,
    "fixed_price": float,
    "price_currency": Currency,
    "delivery_start_month": date.fromisoformat,
    "delivery_end_month": date.fromisoformat,
    "floating_index": str,
}


def _coerce_amendment_value(field: str, raw: Any) -> Any:
    coercer = _FIELD_COERCERS[field]
    return raw if isinstance(raw, date) else coercer(raw)


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
        self._session = session
        self._repo = TradeRepository(session)
        self._change_repo = TradeChangeRequestRepository(session)

    async def create_trade(self, payload: TradeCreate, actor: User) -> Trade:
        trade = Trade(**payload.model_dump(), created_by_user_id=actor.id)
        trade = await self._repo.add(trade)
        await record_audit_event(
            self._session,
            entity_type="Trade",
            entity_id=trade.id,
            action=AuditAction.CREATE,
            actor_user_id=actor.id,
            after=_trade_snapshot(trade),
        )
        await self._session.commit()
        await self._session.refresh(trade, attribute_names=["counterparty", "book"])
        return trade

    async def get_trade(self, trade_id: uuid.UUID) -> Trade:
        trade = await self._repo.get(trade_id)
        if trade is None:
            raise NotFoundError("Trade", trade_id)
        return trade

    async def list_trades(
        self, *, book_id: uuid.UUID | None = None, limit: int = 100, offset: int = 0
    ) -> list[Trade]:
        return await self._repo.list(book_id=book_id, limit=limit, offset=offset)

    async def confirm_trade(self, trade_id: uuid.UUID, actor: User) -> Trade:
        trade = await self.get_trade(trade_id)
        if trade.status != TradeStatus.NEW:
            raise ValidationFailedError(f"cannot confirm a trade in status {trade.status}")
        before = _trade_snapshot(trade)
        trade.status = TradeStatus.CONFIRMED
        await self._session.flush()
        await record_audit_event(
            self._session,
            entity_type="Trade",
            entity_id=trade.id,
            action=AuditAction.CONFIRM,
            actor_user_id=actor.id,
            before=before,
            after=_trade_snapshot(trade),
        )
        await self._session.commit()
        # `updated_at` has an onupdate=func.now() server-side default: after an UPDATE,
        # SQLAlchemy marks it (only it, regardless of expire_on_commit) as needing a
        # fresh SELECT to learn what the server actually computed. Without this
        # refresh, the router's synchronous Pydantic validation would trigger that
        # SELECT itself and fail with MissingGreenlet (implicit IO outside an await).
        await self._session.refresh(trade)
        return trade

    async def request_amendment(
        self, trade_id: uuid.UUID, payload: AmendmentRequestCreate, actor: User
    ) -> TradeChangeRequest:
        trade = await self.get_trade(trade_id)
        if trade.status != TradeStatus.CONFIRMED:
            raise ValidationFailedError("can only request an amendment on a CONFIRMED trade")

        change_request = TradeChangeRequest(
            trade_id=trade.id,
            change_type=ChangeRequestType.AMENDMENT,
            proposed_changes=payload.changes,
            reason=payload.reason,
            requested_by_user_id=actor.id,
        )
        change_request = await self._change_repo.add(change_request)

        before = _trade_snapshot(trade)
        trade.status = TradeStatus.PENDING_AMENDMENT
        await self._session.flush()
        await record_audit_event(
            self._session,
            entity_type="Trade",
            entity_id=trade.id,
            action=AuditAction.REQUEST_AMENDMENT,
            actor_user_id=actor.id,
            before=before,
            after=_trade_snapshot(trade),
            note=payload.reason,
        )
        await self._session.commit()
        await self._session.refresh(change_request)
        return change_request

    async def request_cancellation(
        self, trade_id: uuid.UUID, payload: CancellationRequestCreate, actor: User
    ) -> TradeChangeRequest:
        trade = await self.get_trade(trade_id)
        if trade.status != TradeStatus.CONFIRMED:
            raise ValidationFailedError("can only request cancellation on a CONFIRMED trade")

        change_request = TradeChangeRequest(
            trade_id=trade.id,
            change_type=ChangeRequestType.CANCELLATION,
            proposed_changes=None,
            reason=payload.reason,
            requested_by_user_id=actor.id,
        )
        change_request = await self._change_repo.add(change_request)

        before = _trade_snapshot(trade)
        trade.status = TradeStatus.PENDING_CANCELLATION
        await self._session.flush()
        await record_audit_event(
            self._session,
            entity_type="Trade",
            entity_id=trade.id,
            action=AuditAction.REQUEST_CANCELLATION,
            actor_user_id=actor.id,
            before=before,
            after=_trade_snapshot(trade),
            note=payload.reason,
        )
        await self._session.commit()
        await self._session.refresh(change_request)
        return change_request

    async def list_pending_change_requests(self) -> list[TradeChangeRequest]:
        return await self._change_repo.list_pending()

    async def get_change_request(self, change_request_id: uuid.UUID) -> TradeChangeRequest:
        change_request = await self._change_repo.get(change_request_id)
        if change_request is None:
            raise NotFoundError("TradeChangeRequest", change_request_id)
        return change_request

    async def approve_change_request(
        self, change_request_id: uuid.UUID, actor: User, note: str | None
    ) -> TradeChangeRequest:
        change_request = await self.get_change_request(change_request_id)
        self._check_pending_and_four_eyes(change_request, actor)

        trade = await self.get_trade(change_request.trade_id)
        before = _trade_snapshot(trade)

        if change_request.change_type == ChangeRequestType.AMENDMENT:
            new_trade = self._apply_amendment(trade, change_request.proposed_changes or {})
            self._session.add(new_trade)
            trade.status = TradeStatus.AMENDED
            await self._session.flush()
            await record_audit_event(
                self._session,
                entity_type="Trade",
                entity_id=trade.id,
                action=AuditAction.APPROVE_CHANGE,
                actor_user_id=actor.id,
                before=before,
                after=_trade_snapshot(trade),
                note=f"amendment approved; superseded by trade {new_trade.id}",
            )
            await record_audit_event(
                self._session,
                entity_type="Trade",
                entity_id=new_trade.id,
                action=AuditAction.CREATE,
                actor_user_id=actor.id,
                after=_trade_snapshot(new_trade),
                note=f"created via approved amendment of trade {trade.id}",
            )
        else:
            trade.status = TradeStatus.CANCELLED
            await self._session.flush()
            await record_audit_event(
                self._session,
                entity_type="Trade",
                entity_id=trade.id,
                action=AuditAction.APPROVE_CHANGE,
                actor_user_id=actor.id,
                before=before,
                after=_trade_snapshot(trade),
                note="cancellation approved",
            )

        change_request.status = ChangeRequestStatus.APPROVED
        change_request.reviewed_by_user_id = actor.id
        change_request.reviewed_at = datetime.now(timezone.utc)
        change_request.review_note = note
        await self._session.commit()
        await self._session.refresh(change_request)
        return change_request

    async def reject_change_request(
        self, change_request_id: uuid.UUID, actor: User, note: str | None
    ) -> TradeChangeRequest:
        change_request = await self.get_change_request(change_request_id)
        self._check_pending_and_four_eyes(change_request, actor)

        trade = await self.get_trade(change_request.trade_id)
        before = _trade_snapshot(trade)
        trade.status = TradeStatus.CONFIRMED  # revert to the pre-request state
        await self._session.flush()
        await record_audit_event(
            self._session,
            entity_type="Trade",
            entity_id=trade.id,
            action=AuditAction.REJECT_CHANGE,
            actor_user_id=actor.id,
            before=before,
            after=_trade_snapshot(trade),
            note=note,
        )

        change_request.status = ChangeRequestStatus.REJECTED
        change_request.reviewed_by_user_id = actor.id
        change_request.reviewed_at = datetime.now(timezone.utc)
        change_request.review_note = note
        await self._session.commit()
        await self._session.refresh(change_request)
        return change_request

    def _check_pending_and_four_eyes(self, change_request: TradeChangeRequest, actor: User) -> None:
        if change_request.status != ChangeRequestStatus.PENDING:
            raise ValidationFailedError(f"change request is already {change_request.status}")
        if change_request.requested_by_user_id == actor.id:
            raise ValidationFailedError(
                "four-eyes violation: the approver must be a different user than the requester"
            )

    def _apply_amendment(self, trade: Trade, changes: dict[str, Any]) -> Trade:
        current: dict[str, Any] = {
            "trade_type": trade.trade_type,
            "buy_sell": trade.buy_sell,
            "volume": trade.volume,
            "volume_unit": trade.volume_unit,
            "fixed_price": trade.fixed_price,
            "price_currency": trade.price_currency,
            "delivery_start_month": trade.delivery_start_month,
            "delivery_end_month": trade.delivery_end_month,
            "floating_index": trade.floating_index,
        }
        for field, raw_value in changes.items():
            current[field] = _coerce_amendment_value(field, raw_value)

        if float(current["volume"]) <= 0:
            raise ValidationFailedError("volume must be positive")
        if current["delivery_end_month"] < current["delivery_start_month"]:
            raise ValidationFailedError(
                "delivery_end_month must not be before delivery_start_month"
            )

        return Trade(
            trade_date=trade.trade_date,
            counterparty_id=trade.counterparty_id,
            book_id=trade.book_id,
            commodity=trade.commodity,
            created_by_user_id=trade.created_by_user_id,
            status=TradeStatus.CONFIRMED,
            version=trade.version + 1,
            previous_version_id=trade.id,
            **current,
        )
