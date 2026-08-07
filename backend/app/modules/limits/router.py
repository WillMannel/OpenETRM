import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.common.enums import UserRole
from app.common.exceptions import NotFoundError, ValidationFailedError
from app.modules.auth.models import User
from app.modules.limits.schemas import (
    AcknowledgeBreachRequest,
    BookLimitCreate,
    BookLimitRead,
    LimitBreachRead,
)
from app.modules.limits.service import LimitService

router = APIRouter(prefix="/limits", tags=["limits"])

_RISK_OR_ADMIN = require_role(UserRole.RISK_MANAGER, UserRole.ADMIN)


@router.post("", response_model=BookLimitRead, status_code=201)
async def create_or_update_limit(
    payload: BookLimitCreate,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_RISK_OR_ADMIN),
) -> BookLimitRead:
    service = LimitService(session)
    limit = await service.create_or_update_limit(payload, actor)
    return BookLimitRead.model_validate(limit)


@router.get("", response_model=list[BookLimitRead])
async def list_limits(
    book_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_db),
    _actor: User = Depends(_RISK_OR_ADMIN),
) -> list[BookLimitRead]:
    service = LimitService(session)
    return [BookLimitRead.model_validate(limit) for limit in await service.list_limits(book_id)]


@router.get("/breaches", response_model=list[LimitBreachRead])
async def list_open_breaches(
    book_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_db),
    _actor: User = Depends(_RISK_OR_ADMIN),
) -> list[LimitBreachRead]:
    service = LimitService(session)
    return [
        LimitBreachRead.model_validate(breach)
        for breach in await service.list_open_breaches(book_id)
    ]


@router.post("/breaches/{breach_id}/acknowledge", response_model=LimitBreachRead)
async def acknowledge_breach(
    breach_id: uuid.UUID,
    payload: AcknowledgeBreachRequest,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_RISK_OR_ADMIN),
) -> LimitBreachRead:
    service = LimitService(session)
    try:
        breach = await service.acknowledge_breach(breach_id, actor, payload.note)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LimitBreachRead.model_validate(breach)
