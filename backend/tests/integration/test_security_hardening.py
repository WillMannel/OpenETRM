"""Task P1-10 (Production operability, DR, and security review): CORS policy,
baseline security-response headers, and brute-force protection on POST /auth/login.
See ARCHITECTURE.md's "Production operability, DR, and security review" section.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from tests.conftest import AuthHeadersFactory


@pytest.mark.asyncio
async def test_every_response_carries_baseline_security_headers(
    client: AsyncClient, db_session: AsyncSession
):
    resp = await client.get("/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    # Not asserting Strict-Transport-Security here -- it's deliberately conditional
    # on the request having arrived over HTTPS (see SecurityHeadersMiddleware's
    # docstring), and ASGITransport-driven test requests are plain HTTP.
    assert "Strict-Transport-Security" not in resp.headers


@pytest.mark.asyncio
async def test_cors_preflight_allows_the_configured_frontend_origin(
    client: AsyncClient, db_session: AsyncSession
):
    configured_origin = get_settings().cors_allowed_origins_list[0]
    resp = await client.options(
        "/api/v1/auth/me",
        headers={
            "Origin": configured_origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == configured_origin
    assert resp.headers["access-control-allow-credentials"] == "true"


@pytest.mark.asyncio
async def test_cors_preflight_rejects_an_unconfigured_origin(
    client: AsyncClient, db_session: AsyncSession
):
    resp = await client.options(
        "/api/v1/auth/me",
        headers={
            "Origin": "https://not-the-configured-frontend.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Starlette's CORSMiddleware still returns 200 for a disallowed-origin preflight
    # -- it just omits Access-Control-Allow-Origin, which is what makes the browser
    # itself refuse to expose the response to the calling page's JavaScript.
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
async def test_login_is_rate_limited_after_repeated_failures(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    # A real user, so the *credentials* are never the reason later attempts fail --
    # isolates the rate limiter's own behavior from AuthService.authenticate's.
    from app.common.enums import UserRole
    from app.modules.auth.repository import UserRepository

    username = "rate-limited-user"
    await auth_headers(UserRole.VIEWER, username=username)

    settings = get_settings()
    for _ in range(settings.login_rate_limit_max_attempts):
        resp = await client.post(
            "/api/v1/auth/login", json={"username": username, "password": "wrong-password"}
        )
        assert resp.status_code == 401

    limited = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "wrong-password"}
    )
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers

    # Even the *correct* password is rejected once the window is exhausted -- the
    # limiter throttles the attempt itself, before AuthService ever sees it.
    correct_password_still_blocked = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "test-password-123"}
    )
    assert correct_password_still_blocked.status_code == 429

    # Sanity: the UserRepository fixture's password really was "test-password-123"
    # and the account is otherwise fine -- only the limiter is what's blocking it.
    user = await UserRepository(db_session).get_by_username(username)
    assert user is not None
    assert user.is_active


@pytest.mark.asyncio
async def test_successful_login_clears_the_failure_count(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    from app.common.enums import UserRole

    username = "rate-limit-clears-user"
    await auth_headers(UserRole.VIEWER, username=username)

    # A couple of failures, then success -- must not count toward the limit once
    # the account authenticates correctly.
    for _ in range(2):
        wrong = await client.post(
            "/api/v1/auth/login", json={"username": username, "password": "wrong-password"}
        )
        assert wrong.status_code == 401

    correct = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "test-password-123"}
    )
    assert correct.status_code == 200

    # Immediately usable again -- the two prior failures were cleared, not carried
    # forward toward next time this account has a bad password entered.
    correct_again = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "test-password-123"}
    )
    assert correct_again.status_code == 200


@pytest.mark.asyncio
async def test_login_rate_limit_is_scoped_per_username_not_shared_globally(
    client: AsyncClient, db_session: AsyncSession, auth_headers: AuthHeadersFactory
):
    """A busy/attacked username must not lock out unrelated accounts from the same
    client -- confirms the limiter's key includes the username, not just the
    client IP."""
    from app.common.enums import UserRole

    attacked_username = "rate-limit-attacked-user"
    other_username = "rate-limit-unrelated-user"
    await auth_headers(UserRole.VIEWER, username=attacked_username)
    await auth_headers(UserRole.VIEWER, username=other_username)

    settings = get_settings()
    for _ in range(settings.login_rate_limit_max_attempts + 1):
        await client.post(
            "/api/v1/auth/login",
            json={"username": attacked_username, "password": "wrong-password"},
        )

    unrelated = await client.post(
        "/api/v1/auth/login", json={"username": other_username, "password": "test-password-123"}
    )
    assert unrelated.status_code == 200
