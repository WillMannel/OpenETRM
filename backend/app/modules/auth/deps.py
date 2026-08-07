"""FastAPI auth dependencies: get_current_user (decode JWT, load the user) and
require_role (a dependency factory enforcing RBAC). Kept in the auth module rather
than app.api.deps directly so auth's own router can import them without a cycle;
app.api.deps re-exports them for everyone else."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.core.db import get_session
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.auth.security import InvalidTokenError, decode_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
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
