"""Password hashing (bcrypt, directly -- no passlib indirection), JWT encode/decode,
and API key / refresh token generation/hashing. Kept dependency-free of the rest of
the app so it's easy to reason about and unit test in isolation."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.common.enums import UserRole
from app.core.config import get_settings

settings = get_settings()

_JWT_SUBJECT_CLAIM = "sub"
_JWT_ROLE_CLAIM = "role"
_JWT_ID_CLAIM = "jti"

API_KEY_PREFIX = "oetrm_"
REFRESH_TOKEN_PREFIX = "oetrm_rt_"


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


@dataclass(frozen=True)
class IssuedAccessToken:
    token: str
    jti: str
    expires_at: datetime


def create_access_token(user_id: uuid.UUID, role: UserRole | str) -> str:
    """`role` may already be a UserRole, or a plain str if the caller got it straight
    off a freshly-queried ORM object (String-typed columns come back as plain str, not
    re-wrapped as the enum, after a DB round trip) -- UserRole(role) normalizes either.

    Back-compat wrapper around issue_access_token that returns just the token string
    -- most callers (login, tests) don't need the jti/expiry, only whoever needs to
    revoke a *specific* token later (POST /auth/logout) does."""
    return issue_access_token(user_id, role).token


def issue_access_token(user_id: uuid.UUID, role: UserRole | str) -> IssuedAccessToken:
    """Every access token gets a unique `jti` (JWT ID) claim -- not used for anything
    at issuance time, but it's what app.modules.auth.revocation's Redis denylist keys
    on: POST /auth/logout revokes *this specific token* by its jti, without needing to
    invalidate every other token the same user has outstanding on other devices/tabs."""
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    jti = str(uuid.uuid4())
    payload = {
        _JWT_SUBJECT_CLAIM: str(user_id),
        _JWT_ROLE_CLAIM: UserRole(role).value,
        _JWT_ID_CLAIM: jti,
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return IssuedAccessToken(token=token, jti=jti, expires_at=expires_at)


def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_key, key_prefix, hashed_key). `full_key` is returned to the
    caller exactly once (at creation) and never stored -- only `hashed_key` (its
    SHA-256 hex digest) and `key_prefix` (its first 14 characters, for identifying
    which key is which in a list) are persisted. See ApiKey's docstring for why
    SHA-256 rather than bcrypt is the right hash here."""
    full_key = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return full_key, full_key[:14], hash_api_key(full_key)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_refresh_token() -> tuple[str, str]:
    """Returns (full_token, hashed_token) -- same shape and same rationale as
    generate_api_key (a high-entropy random token, not a human-chosen secret, so
    SHA-256 rather than bcrypt is the right hash: see ApiKey's docstring). Only
    hashed_token is ever persisted (RefreshToken.hashed_token); the raw token is
    returned to the client exactly once, at login/refresh time, same discipline as an
    API key's raw value."""
    full_token = f"{REFRESH_TOKEN_PREFIX}{secrets.token_urlsafe(48)}"
    return full_token, hash_api_key(full_token)  # same SHA-256 hash fn, no reason to duplicate it


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class DecodedToken:
    user_id: uuid.UUID
    jti: str
    expires_at: datetime


def decode_access_token(token: str) -> DecodedToken:
    """Returns the token's claims. Raises InvalidTokenError on any failure (expired,
    malformed, wrong signature, missing jti) -- callers map that to a 401. `jti` lets
    a caller (get_current_user) check the token against the revocation denylist
    (app.modules.auth.revocation) without a second decode."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return DecodedToken(
            user_id=uuid.UUID(payload[_JWT_SUBJECT_CLAIM]),
            jti=payload[_JWT_ID_CLAIM],
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc
