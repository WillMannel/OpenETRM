"""A plain (non-Arq) async Redis client, for anything that just needs SET/GET/EXISTS
-- today, the JWT revocation denylist (app.modules.auth.revocation). Deliberately
separate from app.core.jobs.get_arq_pool: that pool is scoped to the job queue's
lifecycle, and coupling auth's revocation checks (on the hot path of nearly every
authenticated request) to Arq's connection would be the wrong dependency direction --
auth shouldn't care whether background jobs exist at all.

Same lazy-singleton-with-test-override pattern as get_arq_pool: cached at module scope
so it's a plain `Depends(get_redis_client)` that tests can override, keeping routes
that never call it Redis-free.
"""

import redis.asyncio as redis_asyncio

from app.core.config import get_settings

settings = get_settings()

_client: redis_asyncio.Redis | None = None


async def get_redis_client() -> redis_asyncio.Redis:
    global _client
    if _client is None:
        _client = redis_asyncio.from_url(settings.redis_url)
    return _client


async def reset_redis_client() -> None:
    """Closes and drops the cached client so the next get_redis_client() call opens a
    fresh connection. Exists for tests that talk to a *real* Redis across more than
    one pytest-asyncio test function in the same process (each gets its own event
    loop by default) -- without this, a connection opened on one test's loop leaks
    into the next, the same "Future attached to a different loop" failure class
    documented on app.core.db.engine and test_worker_e2e.py's module docstring.
    Ordinary request handling never calls this -- one process, one event loop,
    forever, so the cached client is exactly the right lifetime."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
