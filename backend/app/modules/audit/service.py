import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import AuditAction, UserRole
from app.common.exceptions import ForbiddenError
from app.modules.audit.models import AuditLog
from app.modules.audit.repository import AuditRepository
from app.modules.auth.models import User
from app.modules.entitlements.service import EntitlementService
from app.modules.limits.models import LimitBreach
from app.modules.trade_capture.models import Trade

# Every entity_type record_audit_event is ever called with today (see the grep of
# call sites this was built from) -- both are book-scoped. An entity_type not
# handled by _resolve_book_id below falls through to its fail-closed default, so
# adding a new audited entity type here is a should, not a must, for correctness --
# but leaving it out means only ADMIN can view its audit history until it's added.
_BOOK_SCOPED_ENTITY_TYPES = frozenset({"Trade", "LimitBreach"})


async def record_audit_event(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: AuditAction,
    actor_user_id: uuid.UUID | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    note: str | None = None,
) -> AuditLog:
    """Flushes (not commits) the entry -- callers are expected to be inside a
    transaction that also writes the entity change itself, so the audit entry and the
    change it describes commit atomically together."""
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action.value,
        actor_user_id=actor_user_id,
        before=before,
        after=after,
        note=note,
    )
    return await AuditRepository(session).add(entry)


class AuditService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = AuditRepository(session)
        self._entitlement_service = EntitlementService(session)

    async def history_for(
        self, entity_type: str, entity_id: uuid.UUID, *, actor: User
    ) -> list[AuditLog]:
        """Audit entries carry a full before/after economic snapshot (see
        `TradeCaptureService._trade_snapshot`) -- this must be at least as
        restrictive as reading the entity itself, or a Desk B user could read Desk
        A's trade economics through the audit trail even though every other
        book-scoped endpoint (trade_capture, valuation, risk, limits, export)
        enforces `EntitlementService.assert_can_access_book` (see
        ARCHITECTURE.md's "Book-level entitlements" and "Internal security-review
        pass" sections -- this endpoint was originally shipped before entitlements
        existed and was never updated when they were added)."""
        await self._assert_can_view(entity_type, entity_id, actor)
        return await self._repo.list_for_entity(entity_type, entity_id)

    async def _assert_can_view(self, entity_type: str, entity_id: uuid.UUID, actor: User) -> None:
        if entity_type not in _BOOK_SCOPED_ENTITY_TYPES:
            # An entity type this service doesn't know how to resolve a book_id for
            # -- fail closed rather than silently allow. ADMIN already bypasses
            # every book-level check; nobody else can view an entity type this
            # doesn't recognize.
            role = UserRole(actor.role.value if hasattr(actor.role, "value") else actor.role)
            if role != UserRole.ADMIN:
                raise ForbiddenError(
                    f"cannot determine book entitlement for entity_type={entity_type!r}; "
                    "only ADMIN may view its audit history"
                )
            return
        book_id = await self._resolve_book_id(entity_type, entity_id)
        if book_id is None:
            # The entity itself doesn't exist -- list_for_entity will return an empty
            # list regardless, so there's nothing to entitlement-check or leak.
            return
        await self._entitlement_service.assert_can_access_book(actor, book_id)

    async def _resolve_book_id(self, entity_type: str, entity_id: uuid.UUID) -> uuid.UUID | None:
        if entity_type == "Trade":
            trade = await self._session.get(Trade, entity_id)
            return trade.book_id if trade is not None else None
        if entity_type == "LimitBreach":
            breach = await self._session.get(LimitBreach, entity_id)
            return breach.book_id if breach is not None else None
        # Unreachable given _assert_can_view's membership check above; satisfies
        # mypy without a fake default that could silently mask a future mismatch
        # between _BOOK_SCOPED_ENTITY_TYPES and the branches here.
        raise AssertionError(f"no book_id resolver for entity_type={entity_type!r}")
