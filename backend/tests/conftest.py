"""Integration test fixtures: an isolated async SQLite DB per test.

SQLite stands in for Postgres/Timescale in integration tests so the suite runs without
a live database -- it's close enough for the trade-capture/curve-build flows tested here.
Anything touching Postgres/Timescale-only features (hypertables, ARRAY/JSONB columns)
would need a real Postgres fixture instead; v1's schema doesn't use any of those.
"""

import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.common.enums import UserRole
from app.db.base import Base
from app.main import app
from app.modules.auth.models import User
from app.modules.auth.security import create_access_token, hash_password

AuthHeadersFactory = Callable[..., Awaitable[dict[str, str]]]


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
