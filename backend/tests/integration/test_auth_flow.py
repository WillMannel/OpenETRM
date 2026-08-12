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


async def _register_and_login(client: AsyncClient, username: str, password: str = "supersecret1"):
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    assert register_resp.status_code == 201
    login_resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert login_resp.status_code == 200
    return login_resp.json()


@pytest.mark.asyncio
async def test_login_returns_both_an_access_and_refresh_token(
    client: AsyncClient, db_session: AsyncSession
):
    tokens = await _register_and_login(client, "tokenpair-user")
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["access_token"] != tokens["refresh_token"]


@pytest.mark.asyncio
async def test_logout_revokes_the_access_token_used_to_call_it(
    client: AsyncClient, db_session: AsyncSession
):
    tokens = await _register_and_login(client, "logout-user")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # The token works before logout...
    me_before = await client.get("/api/v1/auth/me", headers=headers)
    assert me_before.status_code == 200

    logout_resp = await client.post("/api/v1/auth/logout", json={}, headers=headers)
    assert logout_resp.status_code == 204

    # ...and is rejected (revoked, not just "still structurally valid") after.
    me_after = await client.get("/api/v1/auth/me", headers=headers)
    assert me_after.status_code == 401


@pytest.mark.asyncio
async def test_logout_also_revokes_the_refresh_token_when_provided(
    client: AsyncClient, db_session: AsyncSession
):
    tokens = await _register_and_login(client, "logout-refresh-user")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    logout_resp = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers
    )
    assert logout_resp.status_code == 204

    refresh_resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh_resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_is_a_silent_no_op_when_the_bearer_token_isnt_a_local_one(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    # POST /auth/logout requires *some* currently-valid principal (get_current_user),
    # so it can be called authenticated via an API key. If a stray/garbage bearer
    # token rides along too, there's nothing of ours to revoke for it -- that must be
    # a silent no-op, not a failure, since logout should never leak whether a
    # presented token was ever one of ours.
    from app.common.enums import UserRole

    admin_headers = await auth_headers(UserRole.ADMIN)
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "logout-svc-acct",
            "email": "logout-svc-acct@example.com",
            "password": "supersecret1",
        },
    )
    assert register_resp.status_code == 201
    user_id = register_resp.json()["id"]

    create_key_resp = await client.post(
        f"/api/v1/auth/users/{user_id}/api-keys",
        json={"name": "logout test key"},
        headers=admin_headers,
    )
    assert create_key_resp.status_code == 201
    api_key = create_key_resp.json()["api_key"]

    resp = await client.post(
        "/api/v1/auth/logout",
        json={},
        headers={"X-API-Key": api_key, "Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_refresh_issues_a_new_pair_and_invalidates_the_old_refresh_token(
    client: AsyncClient, db_session: AsyncSession
):
    tokens = await _register_and_login(client, "refresh-user")

    refreshed_resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed_resp.status_code == 200
    refreshed = refreshed_resp.json()
    assert refreshed["access_token"] != tokens["access_token"]
    assert refreshed["refresh_token"] != tokens["refresh_token"]

    # The new access token actually authenticates.
    me_resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {refreshed['access_token']}"}
    )
    assert me_resp.status_code == 200

    # The old refresh token was single-use -- rotated away, not reusable.
    reuse_resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert reuse_resp.status_code == 401


@pytest.mark.asyncio
async def test_reusing_a_rotated_refresh_token_revokes_the_whole_chain(
    client: AsyncClient, db_session: AsyncSession
):
    """Reuse of an already-rotated refresh token is treated as a possible compromise:
    it revokes every token descended from the reused one, not just the reused token
    itself -- so a stolen, already-rotated-away token can't be used to keep a
    legitimate session's later-issued refresh token alive either."""
    tokens = await _register_and_login(client, "chain-revoke-user")

    first_refresh_resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert first_refresh_resp.status_code == 200
    rotated = first_refresh_resp.json()

    # Replay the original (already-rotated-away) refresh token -- reuse detected.
    reuse_resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert reuse_resp.status_code == 401

    # The legitimate, currently-active descendant is now revoked too -- forcing a
    # real re-login rather than leaving a still-usable token for whoever has it.
    second_refresh_resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert second_refresh_resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rejects_garbage_and_unknown_tokens(
    client: AsyncClient, db_session: AsyncSession
):
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert resp.status_code == 401
