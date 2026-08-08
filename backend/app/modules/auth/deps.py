"""FastAPI auth dependencies: get_current_user (resolve a JWT bearer token OR an
X-API-Key header to a User) and require_role (a dependency factory enforcing RBAC).
Kept in the auth module rather than app.api.deps directly so auth's own router can
import them without a cycle; app.api.deps re-exports them for everyone else."""

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.core.db import get_session
from app.modules.auth.models import User
from app.modules.auth.repository import ApiKeyRepository, UserRepository
from app.modules.auth.security import InvalidTokenError, decode_access_token, hash_api_key

_bearer_scheme = HTTPBearer(auto_error=False)
_api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _resolve_api_key(api_key: str, session: AsyncSession) -> User:
    """API keys are the machine-to-machine path -- a BI/pipeline tool (Fabric Data
    Factory, a cron job, ...) authenticating as a service-account User without an
    interactive login flow. See ApiKey's docstring for why it resolves to a User
    rather than being its own principal type."""
    repo = ApiKeyRepository(session)
    stored = await repo.get_by_hash(hash_api_key(api_key))
    if stored is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    if stored.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key has been revoked")
    if stored.expires_at is not None and stored.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key has expired")

    user = await UserRepository(session).get_by_id(stored.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")

    await repo.touch_last_used(stored)
    return user


async def get_current_user(
    api_key: str | None = Depends(_api_key_scheme),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    # X-API-Key takes precedence when both are present -- a caller that sends an API
    # key clearly intends machine-to-machine auth, not a leftover interactive header.
    if api_key is not None:
        return await _resolve_api_key(api_key, session)

    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    user = await UserRepository(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def require_role(*allowed_roles: UserRole):
    """`Depends(require_role(UserRole.TRADER, UserRole.ADMIN))` -- 403s anyone whose
    role isn't in the allowed set. Compose with get_current_user's 401 (not
    authenticated) as a separate, earlier failure mode."""

    async def _check(user: User = Depends(get_current_user)) -> User:
        # user.role may be a plain str (a fresh-from-DB ORM object on a String-typed
        # column comes back that way, not re-wrapped as UserRole) or the real enum --
        # UserRole(...) normalizes either before comparing/formatting.
        role = UserRole(user.role)
        if role not in allowed_roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"role {role.value} may not perform this action (requires one of "
                f"{[r.value for r in allowed_roles]})",
            )
        return user

    return _check
