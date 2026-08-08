import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from tests.conftest import AuthHeadersFactory


async def _register_service_account(client: AsyncClient, username: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "supersecret1"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_only_admin_can_mint_api_keys(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    user_id = await _register_service_account(client, "fabric-pipeline")
    trader_headers = await auth_headers(UserRole.TRADER)

    resp = await client.post(
        f"/api/v1/auth/users/{user_id}/api-keys",
        json={"name": "Fabric pipeline"},
        headers=trader_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_api_key_authenticates_as_its_service_account_user(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    user_id = await _register_service_account(client, "fabric-pipeline-2")
    admin_headers = await auth_headers(UserRole.ADMIN)

    create_resp = await client.post(
        f"/api/v1/auth/users/{user_id}/api-keys",
        json={"name": "Fabric pipeline"},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["api_key"].startswith("oetrm_")
    assert body["key_prefix"] == body["api_key"][:14]

    me_resp = await client.get("/api/v1/auth/me", headers={"X-API-Key": body["api_key"]})
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "fabric-pipeline-2"
    assert me_resp.json()["role"] == "VIEWER"  # self-registration always lands as VIEWER


@pytest.mark.asyncio
async def test_revoked_api_key_is_rejected(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    user_id = await _register_service_account(client, "fabric-pipeline-3")
    admin_headers = await auth_headers(UserRole.ADMIN)

    create_resp = await client.post(
        f"/api/v1/auth/users/{user_id}/api-keys",
        json={"name": "Fabric pipeline"},
        headers=admin_headers,
    )
    api_key = create_resp.json()["api_key"]
    api_key_id = create_resp.json()["id"]

    # works before revocation
    before = await client.get("/api/v1/auth/me", headers={"X-API-Key": api_key})
    assert before.status_code == 200

    revoke_resp = await client.post(
        f"/api/v1/auth/api-keys/{api_key_id}/revoke", headers=admin_headers
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["revoked_at"] is not None

    after = await client.get("/api/v1/auth/me", headers={"X-API-Key": api_key})
    assert after.status_code == 401

    # revoking an already-revoked key is a 422, not a silent no-op
    double_revoke = await client.post(
        f"/api/v1/auth/api-keys/{api_key_id}/revoke", headers=admin_headers
    )
    assert double_revoke.status_code == 422


@pytest.mark.asyncio
async def test_garbage_api_key_is_rejected(client: AsyncClient, db_session: AsyncSession):
    resp = await client.get("/api/v1/auth/me", headers={"X-API-Key": "oetrm_not-a-real-key"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_api_key_takes_precedence_over_a_stale_bearer_token(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """A caller sending both headers clearly intends machine-to-machine auth via the
    API key -- an invalid/expired leftover bearer token alongside it must not 401 the
    request when the API key itself is valid."""
    user_id = await _register_service_account(client, "fabric-pipeline-4")
    admin_headers = await auth_headers(UserRole.ADMIN)

    create_resp = await client.post(
        f"/api/v1/auth/users/{user_id}/api-keys",
        json={"name": "Fabric pipeline"},
        headers=admin_headers,
    )
    api_key = create_resp.json()["api_key"]

    resp = await client.get(
        "/api/v1/auth/me",
        headers={"X-API-Key": api_key, "Authorization": "Bearer garbage-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "fabric-pipeline-4"


@pytest.mark.asyncio
async def test_list_and_create_api_keys_require_the_service_account_user_to_exist(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    admin_headers = await auth_headers(UserRole.ADMIN)
    resp = await client.post(
        f"/api/v1/auth/users/{uuid.uuid4()}/api-keys",
        json={"name": "orphan"},
        headers=admin_headers,
    )
    assert resp.status_code == 404
