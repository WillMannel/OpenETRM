import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from tests.conftest import AuthHeadersFactory


@pytest.mark.asyncio
async def test_register_then_login_then_me(client: AsyncClient, db_session: AsyncSession):
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "newtrader",
            "email": "newtrader@example.com",
            "password": "supersecret1",
        },
    )
    assert register_resp.status_code == 201
    # self-registration always lands as VIEWER, regardless of what's requested
    assert register_resp.json()["role"] == "VIEWER"

    login_resp = await client.post(
        "/api/v1/auth/login", json={"username": "newtrader", "password": "supersecret1"}
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    me_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "newtrader"


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(client: AsyncClient, db_session: AsyncSession):
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "someone",
            "email": "someone@example.com",
            "password": "correctpassword1",
        },
    )

    resp = await client.post(
        "/api/v1/auth/login", json={"username": "someone", "password": "wrongpassword1"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_rejects_duplicate_username(client: AsyncClient, db_session: AsyncSession):
    payload = {"username": "dupe", "email": "dupe@example.com", "password": "supersecret1"}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_protected_endpoint_rejects_missing_and_garbage_tokens(
    client: AsyncClient, db_session: AsyncSession
):
    no_token = await client.get("/api/v1/auth/me")
    assert no_token.status_code == 401

    garbage_token = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert garbage_token.status_code == 401


@pytest.mark.asyncio
async def test_only_admin_can_create_users_with_elevated_roles(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    viewer_headers = await auth_headers(UserRole.VIEWER)
    denied = await client.post(
        "/api/v1/auth/users",
        json={
            "username": "hopeful",
            "email": "hopeful@example.com",
            "password": "supersecret1",
            "role": "ADMIN",
        },
        headers=viewer_headers,
    )
    assert denied.status_code == 403

    admin_headers = await auth_headers(UserRole.ADMIN)
    created = await client.post(
        "/api/v1/auth/users",
        json={
            "username": "provisioned-trader",
            "email": "provisioned@example.com",
            "password": "supersecret1",
            "role": "TRADER",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    assert created.json()["role"] == "TRADER"

    users = await client.get("/api/v1/auth/users", headers=admin_headers)
    assert users.status_code == 200
    assert any(u["username"] == "provisioned-trader" for u in users.json())
