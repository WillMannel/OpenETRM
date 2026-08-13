import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import ApiKey, RefreshToken, User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, user: User) -> User:
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def get_by_username(self, username: str) -> User | None:
        result = await self._session.execute(select(User).where(User.username == username))
        return result.scalars().first()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_oidc_subject(self, oidc_subject: str) -> User | None:
        result = await self._session.execute(select(User).where(User.oidc_subject == oidc_subject))
        return result.scalars().first()

    async def list_all(self) -> list[User]:
        result = await self._session.execute(select(User).order_by(User.username))
        return list(result.scalars().all())


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, token: RefreshToken) -> RefreshToken:
        """Flushes, doesn't commit -- AuthService.refresh combines issuing a new
        token with revoking the old one in a single transaction, same
        flush-then-commit pattern TradeCaptureService established."""
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_by_hash(self, hashed_token: str) -> RefreshToken | None:
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.hashed_token == hashed_token)
        )
        return result.scalars().first()

    async def get(self, token_id: uuid.UUID) -> RefreshToken | None:
        return await self._session.get(RefreshToken, token_id)


class ApiKeyRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, api_key: ApiKey) -> ApiKey:
        self._session.add(api_key)
        await self._session.commit()
        await self._session.refresh(api_key)
        return api_key

    async def get(self, api_key_id: uuid.UUID) -> ApiKey | None:
        return await self._session.get(ApiKey, api_key_id)

    async def get_by_hash(self, hashed_key: str) -> ApiKey | None:
        result = await self._session.execute(select(ApiKey).where(ApiKey.hashed_key == hashed_key))
        return result.scalars().first()

    async def list_for_user(self, user_id: uuid.UUID) -> list[ApiKey]:
        result = await self._session.execute(
            select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def touch_last_used(self, api_key: ApiKey) -> None:
        """Best-effort bookkeeping on the auth hot path -- commits on its own so a
        failure here can never block the request it's timestamping."""
        api_key.last_used_at = datetime.now(timezone.utc)
        await self._session.commit()
