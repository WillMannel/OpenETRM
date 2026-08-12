import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dates import ensure_utc
from app.common.enums import UserRole
from app.common.exceptions import NotFoundError, ValidationFailedError
from app.core.config import get_settings
from app.modules.auth.models import ApiKey, RefreshToken, User
from app.modules.auth.repository import ApiKeyRepository, RefreshTokenRepository, UserRepository
from app.modules.auth.schemas import AdminUserCreate, ApiKeyCreate, LoginRequest, UserRegister
from app.modules.auth.security import (
    generate_api_key,
    generate_refresh_token,
    hash_api_key,
    hash_password,
    issue_access_token,
    verify_password,
)


class RefreshTokenError(ValidationFailedError):
    """A refresh token that's missing, expired, revoked, or already rotated away."""


@dataclass(frozen=True)
class IssuedTokenPair:
    access_token: str
    refresh_token: str


class AuthService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._repo = UserRepository(session)
        self._api_key_repo = ApiKeyRepository(session)
        self._refresh_repo = RefreshTokenRepository(session)

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

    async def authenticate(self, payload: LoginRequest) -> IssuedTokenPair:
        """Returns a fresh access + refresh token pair, or raises
        ValidationFailedError on bad credentials/inactive account -- deliberately the
        same error for "no such user" and "wrong password" so login doesn't leak which
        usernames exist."""
        user = await self._repo.get_by_username(payload.username)
        if (
            user is None
            or not user.is_active
            or not verify_password(payload.password, user.hashed_password)
        ):
            raise ValidationFailedError("invalid username or password")
        return await self._issue_token_pair(user)

    async def _issue_token_pair(self, user: User) -> IssuedTokenPair:
        access_token = issue_access_token(user.id, user.role).token
        raw_refresh, hashed_refresh = generate_refresh_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=get_settings().jwt_refresh_token_expire_days
        )
        await self._refresh_repo.add(
            RefreshToken(user_id=user.id, hashed_token=hashed_refresh, expires_at=expires_at)
        )
        await self._session.commit()
        return IssuedTokenPair(access_token=access_token, refresh_token=raw_refresh)

    async def refresh(self, raw_refresh_token: str) -> IssuedTokenPair:
        """Exchanges a valid, unexpired, unrevoked, not-yet-rotated refresh token for
        a brand new access + refresh token pair, revoking the presented token in the
        same transaction (rotation: each refresh token is single-use). Raises
        RefreshTokenError on any failure.

        Reuse detection: if the presented token has already been rotated away
        (`replaced_by_id` is set), that's not a normal "expired token" case -- it
        means either the same legitimate client is retrying a request whose response
        it never saw (benign), or a stolen copy of an already-used token is being
        replayed alongside the legitimate client (an active compromise). This
        implementation can't distinguish those two cases with the request in front of
        it, so it takes the safer of the two available actions and revokes the
        *entire* chain from this token forward (see _revoke_chain_from), forcing a
        real re-login -- rather than either silently accepting the replay or treating
        every legitimate retry as an attack with no recovery."""
        hashed = hash_api_key(raw_refresh_token)
        stored = await self._refresh_repo.get_by_hash(hashed)
        if stored is None:
            raise RefreshTokenError("invalid refresh token")
        if stored.replaced_by_id is not None or stored.revoked_at is not None:
            await self._revoke_chain_from(stored)
            raise RefreshTokenError(
                "refresh token has already been used -- it and every token issued "
                "from it have been revoked; log in again"
            )
        if ensure_utc(stored.expires_at) <= datetime.now(timezone.utc):
            raise RefreshTokenError("refresh token has expired")

        user = await self._repo.get_by_id(stored.user_id)
        if user is None or not user.is_active:
            raise RefreshTokenError("user not found or inactive")

        access_token = issue_access_token(user.id, user.role).token
        raw_new_refresh, hashed_new_refresh = generate_refresh_token()
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=get_settings().jwt_refresh_token_expire_days
        )
        new_token = await self._refresh_repo.add(
            RefreshToken(user_id=user.id, hashed_token=hashed_new_refresh, expires_at=expires_at)
        )
        stored.revoked_at = datetime.now(timezone.utc)
        stored.replaced_by_id = new_token.id
        await self._session.commit()
        return IssuedTokenPair(access_token=access_token, refresh_token=raw_new_refresh)

    async def _revoke_chain_from(self, token: RefreshToken) -> None:
        """Revokes `token` and walks forward through `replaced_by_id` to revoke every
        token that was ever rotated from it, so a detected-reuse doesn't leave a
        still-valid descendant token usable by whoever legitimately has it -- the
        whole point of treating reuse as a possible compromise is that the safe
        response is "start over from a real login," not "just block this one token.\""""
        current: RefreshToken | None = token
        while current is not None:
            current.revoked_at = current.revoked_at or datetime.now(timezone.utc)
            current = (
                await self._refresh_repo.get(current.replaced_by_id)
                if current.replaced_by_id is not None
                else None
            )
        await self._session.commit()

    async def revoke_refresh_token(self, raw_refresh_token: str) -> None:
        """Used by POST /auth/logout -- best-effort, silent no-op on an
        already-invalid token (logout isn't the place to reveal whether a presented
        token was ever valid)."""
        hashed = hash_api_key(raw_refresh_token)
        stored = await self._refresh_repo.get_by_hash(hashed)
        if stored is None or stored.revoked_at is not None:
            return
        stored.revoked_at = datetime.now(timezone.utc)
        await self._session.commit()

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
