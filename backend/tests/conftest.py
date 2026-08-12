"""Integration test fixtures: an isolated async SQLite DB per test.

SQLite stands in for Postgres/Timescale in integration tests so the suite runs without
a live database -- it's close enough for the trade-capture/curve-build flows tested here.
Anything touching Postgres/Timescale-only features (hypertables, ARRAY/JSONB columns)
would need a real Postgres fixture instead; v1's schema doesn't use any of those.
"""

import os

# Must run before any `from app...` import below -- app.core.config.get_settings() is
# called at *module import time* in several places (app.core.db, app.modules.auth
# .security, ...) and is @lru_cache'd process-wide, so whatever ENVIRONMENT/
# JWT_SECRET_KEY are set to the first time any of those modules gets imported is what
# sticks for the rest of the process. Settings.environment defaults to "production"
# (secure by default -- see config.py), which would make the test suite's own JWT
# secret (a fixed, non-secret string, fine for tests) fail the fail-fast check on
# every single test run. setdefault, not direct assignment: a real CI-provided
# JWT_SECRET_KEY/ENVIRONMENT (if ever set) still wins.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-suite-only-not-a-real-secret-" + "x" * 32)

import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.deps import get_db
from app.common.enums import UserRole
from app.core.redis_client import get_redis_client
from app.db.base import Base
from app.main import app
from app.modules.auth.models import User
from app.modules.auth.security import create_access_token, hash_password

AuthHeadersFactory = Callable[..., Awaitable[dict[str, str]]]


class _FakeRedis:
    """In-process stand-in for the bits of redis.asyncio.Redis that
    app.modules.auth.revocation actually uses (set with a TTL, exists). Overriding
    get_redis_client with this -- the same pattern test_async_jobs.py already uses
    for get_arq_pool -- is what keeps the default SQLite-backed test suite genuinely
    Redis-free: without it, get_current_user's revocation check would need a real
    Redis reachable for nearly every authenticated request in the suite, and worse,
    a real redis.asyncio.Redis client cached at module scope (see
    app.core.redis_client's lazy-singleton pattern) would leak connections bound to
    one test function's event loop into the next, exactly the "Future attached to a
    different loop" failure class test_worker_e2e.py's and test_limit_concurrency
    .py's module docstrings describe for the DB engine."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    # One shared instance for the whole test, not a fresh one per Depends() call --
    # otherwise a revocation written by one request (e.g. POST /auth/logout) would
    # vanish before the next request's is_token_revoked check ever saw it, since each
    # call would get its own empty in-memory store.
    fake_redis = _FakeRedis()
    app.dependency_overrides[get_redis_client] = lambda: fake_redis
    async with session_factory() as session:
        yield session

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_headers(db_session: AsyncSession) -> AuthHeadersFactory:
    """`await auth_headers(UserRole.TRADER)` -- creates a user with that role in the
    test DB and returns an `Authorization: Bearer ...` header dict for it."""

    async def _make(role: UserRole = UserRole.ADMIN, username: str | None = None) -> dict[str, str]:
        username = username or f"user-{uuid.uuid4().hex[:8]}"
        user = User(
            username=username,
            email=f"{username}@example.com",
            hashed_password=hash_password("test-password-123"),
            role=role,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        token = create_access_token(user.id, user.role)
        return {"Authorization": f"Bearer {token}"}

    return _make
