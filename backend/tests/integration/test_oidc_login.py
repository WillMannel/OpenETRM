"""End-to-end proof that an externally-issued OIDC bearer token authenticates through
the real HTTP stack (get_current_user's OIDC fallback path -- see
app.modules.auth.deps), not just the oidc.py unit tests in isolation. Same
locally-generated-RSA-keypair-stands-in-for-the-IdP technique as
tests/unit/auth/test_oidc.py.
"""

import time
import uuid
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.auth import oidc as oidc_module

_ISSUER = "https://login.example.com/tenant-id/v2.0"
_AUDIENCE = "test-audience"


@pytest.fixture
def configured_oidc(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    settings = get_settings()
    monkeypatch.setattr(settings, "oidc_issuer", _ISSUER)
    monkeypatch.setattr(settings, "oidc_audience", _AUDIENCE)
    monkeypatch.setattr(settings, "oidc_jwks_url", f"{_ISSUER}/discovery/v2.0/keys")
    monkeypatch.setattr(
        oidc_module,
        "_get_jwks_client",
        lambda jwks_url: SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(key=public_pem)
        ),
    )

    def _issue(subject: str, **extra_claims) -> str:
        claims = {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": subject,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            **extra_claims,
        }
        return jwt.encode(claims, private_pem, algorithm="RS256")

    return _issue


@pytest.mark.asyncio
async def test_oidc_bearer_token_authenticates_and_auto_provisions_a_viewer(
    client: AsyncClient, db_session: AsyncSession, configured_oidc
):
    subject = f"sub-{uuid.uuid4()}"
    token = configured_oidc(subject, preferred_username="sso.viewer")

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "VIEWER"

    # Logging in again with the same subject resolves to the same auto-provisioned
    # user, not a fresh one each time.
    second_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert second_resp.status_code == 200
    assert second_resp.json()["id"] == body["id"]


@pytest.mark.asyncio
async def test_oidc_bearer_token_with_wrong_audience_is_rejected(
    client: AsyncClient, db_session: AsyncSession, configured_oidc
):
    token = configured_oidc(f"sub-{uuid.uuid4()}")
    # Tamper with the audience the server expects, not the token -- simulate a token
    # minted for a *different* application trying to be replayed against this one.
    settings = get_settings()
    settings.oidc_audience = "some-other-application"

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bearer_token_that_is_neither_a_local_jwt_nor_valid_oidc_is_rejected(
    client: AsyncClient, db_session: AsyncSession, configured_oidc
):
    # configured_oidc turns OIDC on; a garbage bearer token must still 401, not 500.
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer complete-garbage"})
    assert resp.status_code == 401
