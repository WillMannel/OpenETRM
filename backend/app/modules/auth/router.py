import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.common.enums import UserRole
from app.common.exceptions import NotFoundError, ValidationFailedError
from app.modules.auth.deps import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    AdminUserCreate,
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
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


@router.post("/users/{user_id}/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    user_id: uuid.UUID,
    payload: ApiKeyCreate,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> ApiKeyCreated:
    """Admin-only: mint a machine-to-machine credential for a service-account User
    (provision the user via POST /auth/users first -- typically VIEWER, for a
    read-only BI/pipeline integration). `api_key` in the response is the raw key --
    it's shown here exactly once and cannot be retrieved again, only revoked."""
    service = AuthService(session)
    try:
        api_key, raw_key = await service.create_api_key(user_id, payload, admin)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ApiKeyCreated(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        api_key=raw_key,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
    )


@router.get("/users/{user_id}/api-keys", response_model=list[ApiKeyRead])
async def list_api_keys(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN)),
) -> list[ApiKeyRead]:
    service = AuthService(session)
    try:
        keys = await service.list_api_keys(user_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [ApiKeyRead.model_validate(k) for k in keys]


@router.post("/api-keys/{api_key_id}/revoke", response_model=ApiKeyRead)
async def revoke_api_key(
    api_key_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN)),
) -> ApiKeyRead:
    service = AuthService(session)
    try:
        api_key = await service.revoke_api_key(api_key_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ApiKeyRead.model_validate(api_key)
