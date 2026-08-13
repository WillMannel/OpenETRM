"""JWT revocation denylist, backed by Redis.

Access tokens are stateless (HS256, no server-side session row) by design -- that's
what lets get_current_user validate one without a DB round trip on every request. The
tradeoff is the standard one for stateless tokens: there's no row to delete on logout,
so "revoke this token" has to be its own explicit mechanism. A denylist entry keyed by
the token's `jti` (see security.issue_access_token), with a TTL equal to the token's
own remaining lifetime, is the standard fix -- the denylist entry and the token expire
at the same moment, so it never grows unbounded with entries for tokens that would have
expired naturally anyway.
"""

from datetime import datetime, timezone

_REVOKED_KEY_PREFIX = "revoked-jwt:"


def _key(jti: str) -> str:
    return f"{_REVOKED_KEY_PREFIX}{jti}"


async def revoke_token(redis, jti: str, expires_at: datetime) -> None:
    """Adds `jti` to the denylist until `expires_at` -- after that, the token would
    have expired on its own anyway, so there's no need to remember it was revoked."""
    ttl_seconds = max(int((expires_at - datetime.now(timezone.utc)).total_seconds()), 1)
    await redis.set(_key(jti), "1", ex=ttl_seconds)


async def is_token_revoked(redis, jti: str) -> bool:
    return bool(await redis.exists(_key(jti)))
