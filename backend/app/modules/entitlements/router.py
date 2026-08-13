import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_role
from app.common.enums import UserRole
from app.common.exceptions import NotFoundError
from app.modules.auth.models import User
from app.modules.entitlements.schemas import (
    BookDeskAssign,
    BookMembershipCreate,
    BookMembershipRead,
    DeskCreate,
    DeskRead,
)
from app.modules.entitlements.service import EntitlementService

router = APIRouter(tags=["entitlements"])

# Desk separation is itself an access-control boundary -- who may draw or move the
# walls is deliberately narrower than who may operate within them (TRADER/RISK_MANAGER
# elsewhere in the API). ADMIN-only, the same break-glass role EntitlementService
# already treats as bypassing every wall.
_ADMIN_ONLY = require_role(UserRole.ADMIN)


@router.post("/desks", response_model=DeskRead, status_code=201)
async def create_desk(
    payload: DeskCreate,
    session: AsyncSession = Depends(get_db),
    _actor: User = Depends(_ADMIN_ONLY),
) -> DeskRead:
    service = EntitlementService(session)
    desk = await service.create_desk(payload.name, payload.description)
    return DeskRead.model_validate(desk)


@router.get("/desks", response_model=list[DeskRead])
async def list_desks(
    session: AsyncSession = Depends(get_db), _user: User = Depends(get_current_user)
) -> list[DeskRead]:
    service = EntitlementService(session)
    return [DeskRead.model_validate(d) for d in await service.list_desks()]


@router.put("/books/{book_id}/desk", status_code=204)
async def assign_book_desk(
    book_id: uuid.UUID,
    payload: BookDeskAssign,
    session: AsyncSession = Depends(get_db),
    _actor: User = Depends(_ADMIN_ONLY),
) -> None:
    service = EntitlementService(session)
    try:
        await service.assign_book_desk(book_id, payload.desk_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/books/{book_id}/members", response_model=BookMembershipRead, status_code=201)
async def grant_book_membership(
    book_id: uuid.UUID,
    payload: BookMembershipCreate,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(_ADMIN_ONLY),
) -> BookMembershipRead:
    service = EntitlementService(session)
    try:
        membership = await service.grant_membership(book_id, payload.user_id, actor)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return BookMembershipRead.model_validate(membership)


@router.delete("/books/{book_id}/members/{user_id}", status_code=204)
async def revoke_book_membership(
    book_id: uuid.UUID,
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _actor: User = Depends(_ADMIN_ONLY),
) -> None:
    service = EntitlementService(session)
    try:
        await service.revoke_membership(book_id, user_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/books/{book_id}/members", response_model=list[BookMembershipRead])
async def list_book_members(
    book_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _actor: User = Depends(_ADMIN_ONLY),
) -> list[BookMembershipRead]:
    service = EntitlementService(session)
    try:
        memberships = await service.list_memberships(book_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [BookMembershipRead.model_validate(m) for m in memberships]
