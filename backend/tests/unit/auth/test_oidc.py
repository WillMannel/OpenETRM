"""Enterprise SSO: validate_oidc_token / provision_or_get_oidc_user (task #28, P0-6).

No live IdP is needed to test this -- a locally-generated RSA keypair stands in for
the provider's signing key, and oidc._get_jwks_client is monkeypatched to hand back
that key directly instead of PyJWKClient fetching a real JWKS document over the
network. That's the one seam being stubbed; signature verification, iss/aud/exp
checks, and auto-provisioning all run for real against a real (locally-signed) RS256
token.
"""

import time
import uuid
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.core.config import get_settings
from app.modules.auth import oidc as oidc_module
from app.modules.auth.oidc import (
    OidcValidationError,
    provision_or_get_oidc_user,
    validate_oidc_token,
)

_ISSUER = "https://login.example.com/tenant-id/v2.0"
_AUDIENCE = "test-audience"


@pytest.fixture(scope="module")
def rsa_keypair():
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
    return private_pem, public_pem


@pytest.fixture
def configured_oidc(monkeypatch, rsa_keypair):
    """Turns OIDC on with a fake issuer/audience, and stubs the JWKS lookup to hand
    back our locally-generated public key -- no network call, no real IdP."""
    _private_pem, public_pem = rsa_keypair
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
    return settings


def _make_token(
    rsa_keypair,
    *,
    issuer=_ISSUER,
    audience=_AUDIENCE,
    subject="oidc-subject-123",
    extra=None,
    exp_offset=3600,
    omit_sub=False,
):
    private_pem, _public_pem = rsa_keypair
    claims = {
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
    }
    if not omit_sub:
        claims["sub"] = subject
    claims.update(extra or {})
    return jwt.encode(claims, private_pem, algorithm="RS256")


def test_validate_oidc_token_accepts_a_correctly_signed_token(configured_oidc, rsa_keypair):
    token = _make_token(rsa_keypair, extra={"preferred_username": "alice@example.com"})
    claims = validate_oidc_token(token)
    assert claims["sub"] == "oidc-subject-123"
    assert claims["preferred_username"] == "alice@example.com"


def test_validate_oidc_token_rejects_wrong_audience(configured_oidc, rsa_keypair):
    token = _make_token(rsa_keypair, audience="a-different-audience")
    with pytest.raises(OidcValidationError):
        validate_oidc_token(token)


def test_validate_oidc_token_rejects_wrong_issuer(configured_oidc, rsa_keypair):
    token = _make_token(rsa_keypair, issuer="https://not-the-configured-issuer.example.com")
    with pytest.raises(OidcValidationError):
        validate_oidc_token(token)


def test_validate_oidc_token_rejects_expired_token(configured_oidc, rsa_keypair):
    token = _make_token(rsa_keypair, exp_offset=-3600)
    with pytest.raises(OidcValidationError):
        validate_oidc_token(token)


def test_validate_oidc_token_rejects_a_token_missing_sub(configured_oidc, rsa_keypair):
    token = _make_token(rsa_keypair, omit_sub=True)
    with pytest.raises(OidcValidationError):
        validate_oidc_token(token)


def test_validate_oidc_token_rejects_when_oidc_is_not_configured(monkeypatch, rsa_keypair):
    settings = get_settings()
    monkeypatch.setattr(settings, "oidc_issuer", None)
    monkeypatch.setattr(settings, "oidc_audience", None)
    token = _make_token(rsa_keypair)
    with pytest.raises(OidcValidationError):
        validate_oidc_token(token)


@pytest.mark.asyncio
async def test_provision_or_get_oidc_user_creates_a_viewer_on_first_login(
    db_session: AsyncSession,
):
    claims = {"sub": f"sub-{uuid.uuid4()}", "preferred_username": "new.oidc.user"}
    user = await provision_or_get_oidc_user(db_session, claims)
    assert UserRole(user.role) == UserRole.VIEWER
    assert user.oidc_subject == claims["sub"]
    # No usable local password -- this account can only ever authenticate via OIDC.
    assert user.hashed_password.startswith("oidc-no-local-password-")


@pytest.mark.asyncio
async def test_provision_or_get_oidc_user_returns_the_same_user_on_second_login(
    db_session: AsyncSession,
):
    claims = {"sub": f"sub-{uuid.uuid4()}", "preferred_username": "repeat.oidc.user"}
    first = await provision_or_get_oidc_user(db_session, claims)
    second = await provision_or_get_oidc_user(db_session, claims)
    assert first.id == second.id


@pytest.mark.asyncio
async def test_provision_or_get_oidc_user_falls_back_to_a_synthetic_email(
    db_session: AsyncSession,
):
    # A provider that sends neither `email` nor `preferred_username` must still
    # provision successfully -- User.email is NOT NULL + unique.
    claims = {"sub": f"sub-{uuid.uuid4()}"}
    user = await provision_or_get_oidc_user(db_session, claims)
    assert user.email.endswith("@oidc.local")
