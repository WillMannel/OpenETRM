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
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import AuditAction, Commodity, LimitBreachStatus, LimitType
from app.common.exceptions import NotFoundError, ValidationFailedError
from app.common.money import format_decimal
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

    async def lock_volume_limit(self, book_id: uuid.UUID, commodity: Commodity) -> BookLimit | None:
        """Acquires a row lock (`SELECT ... FOR UPDATE`) on the book's VOLUME limit,
        held until the caller's transaction commits or rolls back. This exists to
        close a real check-then-act race: two trades confirmed concurrently in the
        same book+commodity can each individually compute a prospective volume within
        the limit (both reads happen against the same pre-confirm state), yet their
        *combined* effect breaches it -- neither confirm's check ever saw the other's
        change. Locking this row forces the second confirm to wait for the first's
        transaction to finish before it's even allowed to read live trades, so its
        prospective-volume calculation is guaranteed to happen *after* the first's
        change is visible, not concurrently with it.

        Callers MUST call this before re-reading live trades / computing prospective
        volume, and must pass the returned limit to enforce_locked_volume_limit within
        the same transaction -- calling this and then doing the volume read+check
        outside its lock window provides no protection at all. Returns None if no
        VOLUME limit is configured for this book+commodity: nothing to protect, so no
        lock is taken and callers should skip enforcement entirely (a race between two
        confirms is harmless when there's no limit to enforce -- both trades are
        simply allowed to confirm, which is correct).

        Isolation-level note: this relies on Postgres's default READ COMMITTED plus
        row-level locking, not a higher isolation level (REPEATABLE READ/SERIALIZABLE).
        FOR UPDATE's blocking behavior is what actually closes this race -- it forces
        strict ordering between the two transactions -- and that holds regardless of
        isolation level. A higher isolation level would add serialization-failure
        handling (the app would need to catch and retry) for no additional correctness
        benefit here, since we aren't relying on repeatable reads across multiple
        unlocked statements anywhere in this path."""
        return await self._limit_repo.get_by_book_and_type(
            book_id, commodity, LimitType.VOLUME, for_update=True
        )

    async def enforce_locked_volume_limit(
        self,
        limit: BookLimit,
        prospective_max_abs_volume: Decimal,
        as_of_date: date,
        actor: User,
    ) -> None:
        """The second half of the lock_volume_limit pattern: raises LimitBreachError
        (and records the breach) if `prospective_max_abs_volume` -- computed from a
        *fresh* read of live trades taken while holding `limit`'s row lock -- exceeds
        its threshold. Both sides of this comparison are Decimal -- comparing a
        float-cast observed value against a float-cast threshold (as this used to)
        risks the comparison itself flipping right at the boundary due to ordinary
        binary-float rounding, exactly where a limit check most needs to be exact."""
        if prospective_max_abs_volume <= limit.threshold:
            return

        commodity_value = (
            limit.commodity if isinstance(limit.commodity, str) else limit.commodity.value
        )
        await self._record_breach(limit, prospective_max_abs_volume, as_of_date, actor)
        raise LimitBreachError(
            f"confirming this trade would bring book {limit.book_id}'s net {commodity_value} "
            f"volume to {format_decimal(prospective_max_abs_volume)}, exceeding the VOLUME "
            f"limit of {format_decimal(limit.threshold)}"
        )

    async def check_var_limit(
        self,
        book_id: uuid.UUID | None,
        commodity: Commodity,
        confidence_level: int,
        var_value: Decimal,
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
        if var_value <= limit.threshold:
            return None

        return await self._record_breach(limit, var_value, as_of_date, actor)

    async def _record_breach(
        self, limit: BookLimit, observed_value: Decimal, as_of_date: date, actor: User | None
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
                # Stringified, not float-cast -- see trade_capture.service._trade_
                # snapshot's docstring for why an audit record needs the exact value,
                # and json.dumps (the JSON column's default serializer) can't encode
                # Decimal directly.
                "threshold": str(limit.threshold),
                "observed_value": str(observed_value),
            },
        )
        await self._session.commit()
        await self._session.refresh(breach)
        return breach
