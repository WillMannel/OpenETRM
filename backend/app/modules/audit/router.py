import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.common.exceptions import ForbiddenError
from app.modules.audit.schemas import AuditLogRead
from app.modules.audit.service import AuditService
from app.modules.auth.models import User

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/{entity_type}/{entity_id}", response_model=list[AuditLogRead])
async def get_audit_history(
    entity_type: str,
    entity_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> list[AuditLogRead]:
    """Entitlement-checked -- see AuditService.history_for's docstring for why this
    can't be a plain "any authenticated user" read."""
    service = AuditService(session)
    try:
        entries = await service.history_for(entity_type, entity_id, actor=actor)
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return [AuditLogRead.model_validate(e) for e in entries]
