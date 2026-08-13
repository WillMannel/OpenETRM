"""Enterprise SSO: validates an externally-issued OIDC access token (Entra ID, or any
other standards-compliant OIDC provider) via the provider's published JWKS, and
auto-provisions a local User on first login.

This is an *additional* auth path, not a replacement for password login/API keys --
get_current_user tries the local JWT first, then falls back to this only if OIDC is
configured (OIDC_ISSUER set) and the presented bearer token isn't one of ours. A
deployment that never sets OIDC_ISSUER is completely unaffected by this module.

Design notes:
- RS256 (asymmetric) verification against the provider's public signing keys, fetched
  from OIDC_JWKS_URL (or Entra ID's discovery convention if unset -- see
  Settings.get_oidc_jwks_url) and cached by PyJWKClient, which also handles key
  rotation (a `kid` it hasn't seen triggers a re-fetch) -- this app never needs the
  provider's private key or any shared secret, unlike the local HS256 tokens.
- User matching is by the OIDC `sub` claim (User.oidc_subject), not email -- `sub` is
  the one claim every OIDC provider guarantees is stable and unique per user for a
  given issuer+audience; email can change (or be reused after an org's staff turnover)
  in a way `sub` never does.
- Auto-provisioned users default to VIEWER. An admin promotes them via the existing
  POST /auth/users-adjacent path (there's no POST /auth/users equivalent for
  *existing* users' roles yet -- see FUTURE_WORK.md for a PATCH /auth/users/{id}/role
  endpoint as the natural next increment) -- OIDC login is an authentication
  mechanism, not an authorization grant; it must never hand out more than the least
  trusted default role on its own.
"""

import uuid

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.core.config import get_settings
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository

_jwks_client: jwt.PyJWKClient | None = None
_jwks_client_url: str | None = None


class OidcValidationError(Exception):
    pass


def _get_jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    """Cached per JWKS URL (not just unconditionally cached) so switching
    OIDC_JWKS_URL/OIDC_ISSUER in settings -- which only really happens between test
    cases, since get_settings() is itself cached process-wide in real deployments --
    doesn't keep serving keys fetched from the old URL."""
    global _jwks_client, _jwks_client_url
    if _jwks_client is None or _jwks_client_url != jwks_url:
        _jwks_client = jwt.PyJWKClient(jwks_url)
        _jwks_client_url = jwks_url
    return _jwks_client


def validate_oidc_token(token: str) -> dict:
    """Verifies `token`'s signature against the configured provider's published JWKS,
    and its `iss`/`aud` claims against OIDC_ISSUER/OIDC_AUDIENCE. Returns the decoded
    claims dict (at minimum `sub`; `email`/`preferred_username`/`name` if the provider
    sends them) on success. Raises OidcValidationError on any failure -- expired,
    wrong signature, wrong issuer/audience, or OIDC not configured at all."""
    settings = get_settings()
    jwks_url = settings.get_oidc_jwks_url()
    if jwks_url is None or settings.oidc_audience is None:
        raise OidcValidationError("OIDC is not configured on this deployment")

    try:
        signing_key = _get_jwks_client(jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
        )
    except jwt.PyJWTError as exc:
        raise OidcValidationError(f"invalid OIDC token: {exc}") from exc

    if "sub" not in claims:
        raise OidcValidationError("OIDC token is missing the required 'sub' claim")
    return claims


async def provision_or_get_oidc_user(session: AsyncSession, claims: dict) -> User:
    """Looks up a User by claims['sub'] (User.oidc_subject); creates one (VIEWER,
    no usable local password) on first login if none exists. Raises nothing on a
    brand-new subject -- unlike password login, there's no "no such user" failure
    mode here, since a valid, provider-verified identity is by definition allowed to
    exist as a (least-privileged) local user."""
    repo = UserRepository(session)
    existing = await repo.get_by_oidc_subject(claims["sub"])
    if existing is not None:
        return existing

    email = claims.get("email") or claims.get("preferred_username") or f"{claims['sub']}@oidc.local"
    username = _unique_username_from_claims(claims)
    user = User(
        username=username,
        email=email,
        # No local password -- this account can only ever authenticate via OIDC.
        # hash_password("") would be a real (if useless) bcrypt hash of an empty
        # string, which is misleading; a random, never-disclosed, never-typeable
        # value makes "this account has no usable password" explicit in the data.
        hashed_password=f"oidc-no-local-password-{uuid.uuid4()}",
        role=UserRole.VIEWER,
        oidc_subject=claims["sub"],
    )
    return await repo.add(user)


def _unique_username_from_claims(claims: dict) -> str:
    base = claims.get("preferred_username") or claims.get("name") or claims["sub"]
    # Usernames must be unique (User.username has a unique constraint); provider
    # `sub` values are opaque and often long, so a short, still-unique suffix keeps
    # this readable in an admin's user list rather than a wall of GUIDs.
    return f"{base}-{claims['sub'][-8:]}"
