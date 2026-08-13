"""Brute-force protection for POST /auth/login -- see ARCHITECTURE.md's "Production
operability, DR, and security review". A fixed-window counter in Redis, keyed on
(client IP, username): a distributed attacker guessing many usernames from one IP,
or the same username from many IPs, gets throttled on whichever dimension is
actually being hammered, without one busy legitimate IP or one popular shared
username (a service account, say) locking out unrelated traffic.

Deliberately counts *failures*, not attempts: a burst of successful logins (a
legitimate user's several tabs/devices) is never throttled, and a successful login
clears any accumulated failure count for that pair (see clear_login_attempts) --
someone who mistyped their password twice shouldn't stay throttled after getting it
right the third time.
"""

from app.core.config import get_settings

_KEY_PREFIX = "login-attempts:"


class LoginRateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"too many failed login attempts; retry after {retry_after_seconds}s")


def _key(client_ip: str, username: str) -> str:
    return f"{_KEY_PREFIX}{client_ip}:{username}"


async def enforce_login_rate_limit(redis, client_ip: str, username: str) -> None:
    """Call before attempting authentication. Raises LoginRateLimitExceeded if this
    (client_ip, username) pair has already recorded
    Settings.login_rate_limit_max_attempts failures within the current window."""
    settings = get_settings()
    key = _key(client_ip, username)
    attempts = await redis.get(key)
    if attempts is not None and int(attempts) >= settings.login_rate_limit_max_attempts:
        ttl = await redis.ttl(key)
        # A missing/expired TTL (-1/-2) mid-race with the key itself still being
        # readable is vanishingly unlikely but not impossible -- fall back to the
        # full window rather than a nonsensical/negative Retry-After value.
        retry_after = ttl if ttl and ttl > 0 else settings.login_rate_limit_window_seconds
        raise LoginRateLimitExceeded(retry_after_seconds=retry_after)


async def record_login_failure(redis, client_ip: str, username: str) -> None:
    """Increments the fixed-window failure counter, setting its expiry only on the
    first failure in a fresh window (INCR then a conditional EXPIRE, not
    SET-with-TTL) -- concurrent failures for the same pair all still count, rather
    than each one silently resetting the window's start time."""
    settings = get_settings()
    key = _key(client_ip, username)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, settings.login_rate_limit_window_seconds)


async def clear_login_attempts(redis, client_ip: str, username: str) -> None:
    """Called after a successful login."""
    await redis.delete(_key(client_ip, username))
