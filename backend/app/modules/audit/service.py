import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import AuditAction
from app.modules.audit.models import AuditLog
from app.modules.audit.repository import AuditRepository


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
        self._repo = AuditRepository(session)

    async def history_for(self, entity_type: str, entity_id: uuid.UUID) -> list[AuditLog]:
        return await self._repo.list_for_entity(entity_type, entity_id)
