import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.modules.audit.schemas import AuditLogRead
from app.modules.audit.service import AuditService
from app.modules.auth.models import User

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/{entity_type}/{entity_id}", response_model=list[AuditLogRead])
async def get_audit_history(
    entity_type: str,
    entity_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),  # any authenticated user; v1 has no per-book ACLs
) -> list[AuditLogRead]:
    service = AuditService(session)
    entries = await service.history_for(entity_type, entity_id)
    return [AuditLogRead.model_validate(e) for e in entries]
