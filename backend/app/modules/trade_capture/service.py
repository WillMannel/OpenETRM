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
    Commodity,
    Currency,
    OptionType,
    PowerBlock,
    TradeStatus,
    TradeType,
    VolumeUnit,
)
from app.common.exceptions import NotFoundError, ValidationFailedError
from app.modules.audit.service import record_audit_event
from app.modules.auth.models import User
from app.modules.entitlements.service import EntitlementService
from app.modules.limits.service import LimitService
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
from app.modules.valuation.service import ValuationService

_CERTIFICATE_TRADE_TYPES = (TradeType.REC, TradeType.EMISSIONS_ALLOWANCE)


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
        "fixed_price": float(trade.fixed_price) if trade.fixed_price is not None else None,
        "price_currency": _enum_value(trade.price_currency),
        "delivery_start_month": trade.delivery_start_month.isoformat(),
        "delivery_end_month": trade.delivery_end_month.isoformat(),
        "floating_index": trade.floating_index,
        "option_type": _enum_value(trade.option_type) if trade.option_type else None,
        "strike_price": float(trade.strike_price) if trade.strike_price is not None else None,
        "premium": float(trade.premium) if trade.premium is not None else None,
        "option_volatility": (
            float(trade.option_volatility) if trade.option_volatility is not None else None
        ),
        "power_block": _enum_value(trade.power_block) if trade.power_block else None,
        "certificate_registry": trade.certificate_registry,
        "vintage_year": trade.vintage_year,
        "status": _enum_value(trade.status),
        "version": trade.version,
    }


def _optional(coercer: Callable[[Any], Any]) -> Callable[[Any], Any]:
    return lambda raw: None if raw is None else coercer(raw)


_FIELD_COERCERS: dict[str, Callable[[Any], Any]] = {
    "trade_type": TradeType,
    "buy_sell": BuySell,
    "volume": float,
    "volume_unit": VolumeUnit,
    "fixed_price": _optional(float),
    "price_currency": Currency,
    "delivery_start_month": date.fromisoformat,
    "delivery_end_month": date.fromisoformat,
    "floating_index": str,
    "option_type": _optional(OptionType),
    "strike_price": _optional(float),
    "premium": _optional(float),
    "option_volatility": _optional(float),
    "power_block": _optional(PowerBlock),
    "certificate_registry": _optional(str),
    "vintage_year": _optional(int),
}


def _coerce_amendment_value(field: str, raw: Any) -> Any:
    coercer = _FIELD_COERCERS[field]
    if isinstance(raw, date):
        return raw
    try:
        return coercer(raw)
    except (ValueError, TypeError) as exc:
        # e.g. TradeType("BOGUS") or float(None) from a malformed changes payload --
        # AmendmentRequestCreate only validates field *names*, not values, so a bad
        # value only surfaces here. Without this, it would propagate as an unhandled
        # 500 instead of the 422 a bad request deserves.
        raise ValidationFailedError(f"invalid value for {field!r}: {raw!r}") from exc


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
        self._limit_service = LimitService(session)
        self._entitlement_service = EntitlementService(session)

    async def create_trade(self, payload: TradeCreate, actor: User) -> Trade:
        await self._entitlement_service.assert_can_access_book(actor, payload.book_id)
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

    async def get_trade(self, trade_id: uuid.UUID, actor: User) -> Trade:
        trade = await self._repo.get(trade_id)
        if trade is None:
            raise NotFoundError("Trade", trade_id)
        await self._entitlement_service.assert_can_access_book(actor, trade.book_id)
        return trade

    async def list_trades(
        self,
        *,
        actor: User,
        book_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Trade]:
        if book_id is not None:
            await self._entitlement_service.assert_can_access_book(actor, book_id)
            return await self._repo.list(book_id=book_id, limit=limit, offset=offset)
        # No specific book requested -- scope the whole-portfolio listing to whatever
        # this user is entitled to see, rather than leaking every desk's trades.
        accessible = await self._entitlement_service.accessible_book_ids(actor)
        return await self._repo.list(book_ids=accessible, limit=limit, offset=offset)

    async def confirm_trade(self, trade_id: uuid.UUID, actor: User) -> Trade:
        trade = await self.get_trade(trade_id, actor)
        if trade.status != TradeStatus.NEW:
            raise ValidationFailedError(f"cannot confirm a trade in status {trade.status}")

        await self._enforce_volume_limit_for_confirm(trade, actor)

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
        trade = await self.get_trade(trade_id, actor)
        if trade.status != TradeStatus.CONFIRMED:
            raise ValidationFailedError("can only request an amendment on a CONFIRMED trade")

        # Validate now, not just at approval time: nothing else can change `trade`
        # while this request is PENDING (that's the point of PENDING_AMENDMENT), so a
        # payload that's invalid now will still be invalid at approval -- fail fast
        # with a 422 here rather than leaving a doomed request for a risk manager to
        # discover only when they approve it.
        self._apply_amendment(trade, payload.changes)

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
        trade = await self.get_trade(trade_id, actor)
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

    async def list_pending_change_requests(self, actor: User) -> list[TradeChangeRequest]:
        accessible = await self._entitlement_service.accessible_book_ids(actor)
        return await self._change_repo.list_pending(book_ids=accessible)

    async def get_change_request(
        self, change_request_id: uuid.UUID, actor: User
    ) -> TradeChangeRequest:
        change_request = await self._change_repo.get(change_request_id)
        if change_request is None:
            raise NotFoundError("TradeChangeRequest", change_request_id)
        # get_trade enforces entitlement on the change request's underlying trade --
        # a change request is only ever visible to someone who could see that trade.
        await self.get_trade(change_request.trade_id, actor)
        return change_request

    async def approve_change_request(
        self, change_request_id: uuid.UUID, actor: User, note: str | None
    ) -> TradeChangeRequest:
        change_request = await self.get_change_request(change_request_id, actor)
        self._check_pending_and_four_eyes(change_request, actor)

        trade = await self.get_trade(change_request.trade_id, actor)
        before = _trade_snapshot(trade)

        if change_request.change_type == ChangeRequestType.AMENDMENT:
            new_trade = self._apply_amendment(trade, change_request.proposed_changes or {})
            await self._enforce_volume_limit_for_amendment(trade, new_trade, actor)
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
        change_request = await self.get_change_request(change_request_id, actor)
        self._check_pending_and_four_eyes(change_request, actor)

        trade = await self.get_trade(change_request.trade_id, actor)
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

    async def _enforce_volume_limit(
        self,
        book_id: uuid.UUID,
        commodity_raw: Any,
        candidate_trades: list[Trade],
        actor: User,
    ) -> None:
        """Shared by confirm and amendment-approval: raises (and records a breach) if
        `candidate_trades` -- the book's live trades as they would look *after* the
        transition being validated -- would push net volume, in any delivery month,
        past a configured VOLUME limit for this commodity."""
        positions = ValuationService(self._session).build_positions(candidate_trades, date.today())
        prospective_max_abs_volume = max((abs(p.net_volume) for p in positions), default=0.0)
        commodity = Commodity(_enum_value(commodity_raw))
        await self._limit_service.enforce_volume_limit(
            book_id, commodity, prospective_max_abs_volume, date.today(), actor
        )

    async def _enforce_volume_limit_for_confirm(self, trade: Trade, actor: User) -> None:
        """`trade` is still NEW at this point, so it isn't yet counted by
        list_live -- include it explicitly alongside the book's other live trades.
        Scoped to `trade`'s own commodity: an unrelated commodity's position in the
        same book must never count toward this limit (see test_multi_commodity_book.py)."""
        commodity = Commodity(_enum_value(trade.commodity))
        live_trades = await self._repo.list_live(trade.book_id, commodity=commodity)
        await self._enforce_volume_limit(
            trade.book_id, trade.commodity, [*live_trades, trade], actor
        )

    async def _enforce_volume_limit_for_amendment(
        self, original_trade: Trade, new_trade: Trade, actor: User
    ) -> None:
        """`original_trade` is being superseded by `new_trade` (same trade, new
        version) -- check the book's prospective volume with the original trade's
        volume replaced by the amended one, not added alongside it. Commodity isn't
        amendable (see _AMENDABLE_FIELDS), so original_trade and new_trade always share
        one commodity; scoped to it so an unrelated commodity's position in the same
        book never counts toward this limit."""
        commodity = Commodity(_enum_value(new_trade.commodity))
        live_trades = await self._repo.list_live(original_trade.book_id, commodity=commodity)
        other_live_trades = [t for t in live_trades if t.id != original_trade.id]
        await self._enforce_volume_limit(
            original_trade.book_id, new_trade.commodity, [*other_live_trades, new_trade], actor
        )

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
            "option_type": trade.option_type,
            "strike_price": trade.strike_price,
            "premium": trade.premium,
            "option_volatility": trade.option_volatility,
            "power_block": trade.power_block,
            "certificate_registry": trade.certificate_registry,
            "vintage_year": trade.vintage_year,
        }
        for field, raw_value in changes.items():
            current[field] = _coerce_amendment_value(field, raw_value)

        if float(current["volume"]) <= 0:
            raise ValidationFailedError("volume must be positive")
        if current["delivery_end_month"] < current["delivery_start_month"]:
            raise ValidationFailedError(
                "delivery_end_month must not be before delivery_start_month"
            )

        option_fields = ("option_type", "strike_price", "premium", "option_volatility")
        certificate_fields = ("certificate_registry", "vintage_year")

        if current["trade_type"] == TradeType.OPTION:
            missing = [f for f in option_fields if current[f] is None]
            if missing:
                raise ValidationFailedError(f"OPTION trades require: {sorted(missing)}")
            if current["fixed_price"] is not None:
                raise ValidationFailedError("fixed_price does not apply to OPTION trades")
            # Mirrors TradeCreate._check_ranges -- an amendment shouldn't be able to
            # sneak a non-positive strike/vol past the same rule creation enforces.
            if float(current["strike_price"]) <= 0:
                raise ValidationFailedError("strike_price must be positive")
            if float(current["option_volatility"]) <= 0:
                raise ValidationFailedError("option_volatility must be positive")
            if any(current[f] is not None for f in certificate_fields):
                raise ValidationFailedError(
                    "certificate_registry/vintage_year only apply to REC/EMISSIONS_ALLOWANCE trades"
                )
        elif current["trade_type"] in _CERTIFICATE_TRADE_TYPES:
            missing = [f for f in certificate_fields if current[f] is None]
            if missing:
                raise ValidationFailedError(
                    f"{current['trade_type'].value} trades require: {sorted(missing)}"
                )
            if current["fixed_price"] is None:
                raise ValidationFailedError(
                    "fixed_price (price per certificate/allowance) is required"
                )
            if any(current[f] is not None for f in option_fields):
                raise ValidationFailedError("option fields may only be set on an OPTION trade")
        else:
            if current["fixed_price"] is None:
                raise ValidationFailedError("fixed_price is required for SWAP/FORWARD trades")
            if any(current[f] is not None for f in option_fields):
                raise ValidationFailedError("option fields may only be set on an OPTION trade")
            if any(current[f] is not None for f in certificate_fields):
                raise ValidationFailedError(
                    "certificate_registry/vintage_year only apply to REC/EMISSIONS_ALLOWANCE trades"
                )

        # commodity itself isn't amendable (see _AMENDABLE_FIELDS), so re-validate
        # power_block against the trade's fixed, unchangeable commodity -- and, like
        # TradeCreate, only for actual power delivery products (see there for why
        # REC/EMISSIONS_ALLOWANCE are excluded even under commodity=POWER).
        is_power_delivery_product = (
            trade.commodity == Commodity.POWER
            and current["trade_type"] not in _CERTIFICATE_TRADE_TYPES
        )
        if is_power_delivery_product:
            if current["power_block"] is None:
                raise ValidationFailedError(
                    "power_block is required for POWER SWAP/FORWARD/OPTION trades"
                )
        elif current["power_block"] is not None:
            raise ValidationFailedError(
                "power_block only applies to POWER SWAP/FORWARD/OPTION trades"
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
