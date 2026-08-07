import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog


class AuditRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, entry: AuditLog) -> AuditLog:
        self._session.add(entry)
        await self._session.flush()  # visible to the rest of the caller's transaction immediately
        return entry

    async def list_for_entity(self, entity_type: str, entity_id: uuid.UUID) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.occurred_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
