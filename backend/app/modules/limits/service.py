"""Pre-trade and risk limits.

Two limit types, deliberately enforced differently:
- VOLUME limits are checked pre-trade, at trade *confirm* time (a NEW trade doesn't
  move a position yet, so there's nothing to enforce until confirmation would make it
  live) -- a breach blocks the confirm outright (raises, nothing commits).
- VAR limits are checked post-hoc, after a VaR run completes -- a breach is recorded
  and audited but never blocks the run itself; a risk report must always be able to
  report an over-limit number, not hide it.

Both paths record a LimitBreach + an audit_log entry atomically, following the same
flush-then-commit pattern TradeCaptureService established.
"""

import uuid
from datetime import date, timezone
from datetime import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import AuditAction, Commodity, LimitBreachStatus, LimitType
from app.common.exceptions import NotFoundError, ValidationFailedError
from app.modules.audit.service import record_audit_event
from app.modules.auth.models import User
from app.modules.entitlements.service import EntitlementService
from app.modules.limits.models import BookLimit, LimitBreach
from app.modules.limits.repository import LimitBreachRepository, LimitRepository
from app.modules.limits.schemas import BookLimitCreate


class LimitBreachError(ValidationFailedError):
    """A VOLUME limit breach that blocked a trade confirmation."""


class LimitService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._limit_repo = LimitRepository(session)
        self._breach_repo = LimitBreachRepository(session)
        self._entitlement_service = EntitlementService(session)

    async def create_or_update_limit(self, payload: BookLimitCreate, actor: User) -> BookLimit:
        await self._entitlement_service.assert_can_access_book(actor, payload.book_id)
        existing = await self._limit_repo.get_by_book_and_type(
            payload.book_id, payload.commodity, payload.limit_type
        )
        if existing is not None:
            existing.threshold = payload.threshold
            existing.confidence_level = payload.confidence_level
            return await self._limit_repo.add(existing)

        limit = BookLimit(
            book_id=payload.book_id,
            commodity=payload.commodity,
            limit_type=payload.limit_type,
            threshold=payload.threshold,
            confidence_level=payload.confidence_level,
            created_by_user_id=actor.id,
        )
        return await self._limit_repo.add(limit)

    async def list_limits(self, actor: User, book_id: uuid.UUID | None = None) -> list[BookLimit]:
        if book_id is not None:
            await self._entitlement_service.assert_can_access_book(actor, book_id)
            return await self._limit_repo.list_for_book(book_id)
        accessible = await self._entitlement_service.accessible_book_ids(actor)
        return await self._limit_repo.list_for_book(book_ids=accessible)

    async def list_open_breaches(
        self, actor: User, book_id: uuid.UUID | None = None
    ) -> list[LimitBreach]:
        if book_id is not None:
            await self._entitlement_service.assert_can_access_book(actor, book_id)
            return await self._breach_repo.list_open(book_id)
        accessible = await self._entitlement_service.accessible_book_ids(actor)
        return await self._breach_repo.list_open(book_ids=accessible)

    async def acknowledge_breach(
        self, breach_id: uuid.UUID, actor: User, note: str | None
    ) -> LimitBreach:
        breach = await self._breach_repo.get(breach_id)
        if breach is None:
            raise NotFoundError("LimitBreach", breach_id)
        await self._entitlement_service.assert_can_access_book(actor, breach.book_id)
        if breach.status != LimitBreachStatus.OPEN:
            raise ValidationFailedError(f"breach is already {breach.status}")

        breach.status = LimitBreachStatus.ACKNOWLEDGED
        breach.acknowledged_by_user_id = actor.id
        breach.acknowledged_at = dt.now(timezone.utc)
        await self._session.flush()
        await record_audit_event(
            self._session,
            entity_type="LimitBreach",
            entity_id=breach.id,
            action=AuditAction.ACKNOWLEDGE_LIMIT_BREACH,
            actor_user_id=actor.id,
            note=note,
        )
        await self._session.commit()
        await self._session.refresh(breach)
        return breach

    async def enforce_volume_limit(
        self,
        book_id: uuid.UUID,
        commodity: Commodity,
        prospective_max_abs_volume: float,
        as_of_date: date,
        actor: User,
    ) -> None:
        """Raises LimitBreachError (and records the breach) if `prospective_max_abs_volume`
        -- the largest absolute net volume across any delivery month the book would hold
        after the trade in question is confirmed -- exceeds the book's VOLUME limit for
        this commodity. No-op if no such limit is configured."""
        limit = await self._limit_repo.get_by_book_and_type(book_id, commodity, LimitType.VOLUME)
        if limit is None or prospective_max_abs_volume <= float(limit.threshold):
            return

        await self._record_breach(limit, prospective_max_abs_volume, as_of_date, actor)
        raise LimitBreachError(
            f"confirming this trade would bring book {book_id}'s net {commodity.value} "
            f"volume to {prospective_max_abs_volume:g}, exceeding the VOLUME limit of "
            f"{float(limit.threshold):g}"
        )

    async def check_var_limit(
        self,
        book_id: uuid.UUID | None,
        commodity: Commodity,
        confidence_level: int,
        var_value: float,
        as_of_date: date,
        actor: User | None,
    ) -> LimitBreach | None:
        """Non-blocking: records and returns a breach if `var_value` exceeds the book's
        VAR limit at this confidence level, else returns None. book_id=None (whole-book
        aggregate run) has no limit to check against."""
        if book_id is None:
            return None
        limit = await self._limit_repo.get_by_book_and_type(book_id, commodity, LimitType.VAR)
        if limit is None or limit.confidence_level != confidence_level:
            return None
        if var_value <= float(limit.threshold):
            return None

        return await self._record_breach(limit, var_value, as_of_date, actor)

    async def _record_breach(
        self, limit: BookLimit, observed_value: float, as_of_date: date, actor: User | None
    ) -> LimitBreach:
        breach = LimitBreach(
            limit_id=limit.id,
            book_id=limit.book_id,
            commodity=limit.commodity,
            limit_type=limit.limit_type,
            threshold=limit.threshold,
            observed_value=observed_value,
            as_of_date=as_of_date,
        )
        breach = await self._breach_repo.add(breach)
        commodity_value = (
            limit.commodity if isinstance(limit.commodity, str) else limit.commodity.value
        )
        limit_type_value = (
            limit.limit_type if isinstance(limit.limit_type, str) else limit.limit_type.value
        )
        await record_audit_event(
            self._session,
            entity_type="LimitBreach",
            entity_id=breach.id,
            action=AuditAction.LIMIT_BREACH,
            actor_user_id=actor.id if actor is not None else None,
            after={
                "book_id": str(limit.book_id),
                "commodity": commodity_value,
                "limit_type": limit_type_value,
                "threshold": float(limit.threshold),
                "observed_value": observed_value,
            },
        )
        await self._session.commit()
        await self._session.refresh(breach)
        return breach
