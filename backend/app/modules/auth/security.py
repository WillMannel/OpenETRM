"""Password hashing (bcrypt, directly -- no passlib indirection) and JWT
encode/decode. Kept dependency-free of the rest of the app so it's easy to reason
about and unit test in isolation."""

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.common.enums import UserRole
from app.core.config import get_settings

settings = get_settings()

_JWT_SUBJECT_CLAIM = "sub"
_JWT_ROLE_CLAIM = "role"


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(user_id: uuid.UUID, role: UserRole | str) -> str:
    """`role` may already be a UserRole, or a plain str if the caller got it straight
    off a freshly-queried ORM object (String-typed columns come back as plain str, not
    re-wrapped as the enum, after a DB round trip) -- UserRole(role) normalizes either."""
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload = {
        _JWT_SUBJECT_CLAIM: str(user_id),
        _JWT_ROLE_CLAIM: UserRole(role).value,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


class InvalidTokenError(Exception):
    pass


def decode_access_token(token: str) -> uuid.UUID:
    """Returns the user id encoded in the token. Raises InvalidTokenError on any
    failure (expired, malformed, wrong signature) -- callers map that to a 401."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return uuid.UUID(payload[_JWT_SUBJECT_CLAIM])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc
