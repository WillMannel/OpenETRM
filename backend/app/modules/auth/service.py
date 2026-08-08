import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.common.exceptions import NotFoundError, ValidationFailedError
from app.modules.auth.models import ApiKey, User
from app.modules.auth.repository import ApiKeyRepository, UserRepository
from app.modules.auth.schemas import AdminUserCreate, ApiKeyCreate, LoginRequest, UserRegister
from app.modules.auth.security import (
    create_access_token,
    generate_api_key,
    hash_password,
    verify_password,
)


class AuthService:
    def __init__(self, session: AsyncSession):
        self._repo = UserRepository(session)
        self._api_key_repo = ApiKeyRepository(session)

    async def register(self, payload: UserRegister) -> User:
        """Self-service signup. Always VIEWER -- elevated roles come from an admin."""
        return await self._create_user(
            payload.username, payload.email, payload.password, UserRole.VIEWER
        )

    async def create_user_as_admin(self, payload: AdminUserCreate) -> User:
        return await self._create_user(
            payload.username, payload.email, payload.password, payload.role
        )

    async def _create_user(self, username: str, email: str, password: str, role: UserRole) -> User:
        if await self._repo.get_by_username(username) is not None:
            raise ValidationFailedError(f"username already taken: {username}")
        user = User(
            username=username, email=email, hashed_password=hash_password(password), role=role
        )
        return await self._repo.add(user)

    async def authenticate(self, payload: LoginRequest) -> str:
        """Returns a JWT access token, or raises ValidationFailedError on bad
        credentials/inactive account -- deliberately the same error for "no such user"
        and "wrong password" so login doesn't leak which usernames exist."""
        user = await self._repo.get_by_username(payload.username)
        if (
            user is None
            or not user.is_active
            or not verify_password(payload.password, user.hashed_password)
        ):
            raise ValidationFailedError("invalid username or password")
        return create_access_token(user.id, user.role)

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self._repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User", user_id)
        return user

    async def list_users(self) -> list[User]:
        return await self._repo.list_all()

    async def create_api_key(
        self, user_id: uuid.UUID, payload: ApiKeyCreate, actor: User
    ) -> tuple[ApiKey, str]:
        """Returns (the stored ApiKey row, the raw key) -- the raw key is never
        persisted and this is the only call site that ever has it."""
        target_user = await self.get_user(user_id)  # 404s if the service-account user doesn't exist
        if payload.expires_at is not None and payload.expires_at <= datetime.now(timezone.utc):
            raise ValidationFailedError("expires_at must be in the future")

        raw_key, key_prefix, hashed_key = generate_api_key()
        api_key = ApiKey(
            user_id=target_user.id,
            name=payload.name,
            key_prefix=key_prefix,
            hashed_key=hashed_key,
            created_by_user_id=actor.id,
            expires_at=payload.expires_at,
        )
        api_key = await self._api_key_repo.add(api_key)
        return api_key, raw_key

    async def list_api_keys(self, user_id: uuid.UUID) -> list[ApiKey]:
        await self.get_user(user_id)  # 404s if the service-account user doesn't exist
        return await self._api_key_repo.list_for_user(user_id)

    async def revoke_api_key(self, api_key_id: uuid.UUID) -> ApiKey:
        api_key = await self._api_key_repo.get(api_key_id)
        if api_key is None:
            raise NotFoundError("ApiKey", api_key_id)
        if api_key.revoked_at is not None:
            raise ValidationFailedError("API key is already revoked")
        api_key.revoked_at = datetime.now(timezone.utc)
        return await self._api_key_repo.add(api_key)
