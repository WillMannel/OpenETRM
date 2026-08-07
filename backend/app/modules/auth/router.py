from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.common.enums import UserRole
from app.common.exceptions import ValidationFailedError
from app.modules.auth.deps import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    AdminUserCreate,
    LoginRequest,
    TokenResponse,
    UserRead,
    UserRegister,
)
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=201)
async def register(payload: UserRegister, session: AsyncSession = Depends(get_db)) -> UserRead:
    service = AuthService(session)
    try:
        user = await service.register(payload)
    except ValidationFailedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return UserRead.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_db)) -> TokenResponse:
    service = AuthService(session)
    try:
        token = await service.authenticate(payload)
    except ValidationFailedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserRead)
async def get_me(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)


@router.post("/users", response_model=UserRead, status_code=201)
async def create_user(
    payload: AdminUserCreate,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN)),
) -> UserRead:
    """Admin-only: create a user with any role. This is how TRADER/RISK_MANAGER/ADMIN
    accounts get provisioned -- self-registration always lands as VIEWER."""
    service = AuthService(session)
    try:
        user = await service.create_user_as_admin(payload)
    except ValidationFailedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return UserRead.model_validate(user)


@router.get("/users", response_model=list[UserRead])
async def list_users(
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN)),
) -> list[UserRead]:
    service = AuthService(session)
    return [UserRead.model_validate(u) for u in await service.list_users()]
