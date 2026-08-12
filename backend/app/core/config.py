"""Application settings, loaded from environment variables (see .env.example)."""

import logging
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# The exact insecure default shipped in this file, historically. Checked by name (not
# just "is it the current default") so this catches it even if the default value ever
# changes in a later release and someone's env/.env still carries the old one forward.
INSECURE_DEFAULT_JWT_SECRET = "dev-only-insecure-secret-change-me"
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "OpenETRM"
    api_prefix: str = "/api/v1"

    # Secure by default: booting with no ENVIRONMENT set at all (the common failure
    # mode -- an operator who never thought about it) is treated as "production" for
    # the purposes of the secret check below, not "development". A local/dev/test
    # deployment must *opt in* to the relaxed check by setting this explicitly (see
    # docker-compose.yml, tests/conftest.py) -- the safe default requires no one to
    # remember to lock anything down.
    environment: Literal["development", "test", "staging", "production"] = "production"

    database_url: str = "postgresql+asyncpg://openetrm:openetrm@localhost:5432/openetrm"
    redis_url: str = "redis://localhost:6379/0"

    # v1's pilot commodity; Commodity.WTI exists too, to prove the enum isn't hardcoded.
    pilot_commodity: str = "HENRY_HUB"

    # Flat risk-free rate used to discount option cash flows (Black-76). No real yield
    # curve in v1 -- see ARCHITECTURE.md.
    risk_free_rate: float = 0.05

    log_level: str = "INFO"

    # Auth. jwt_secret_key MUST be overridden via env var in any real deployment -- the
    # default here is only so local dev/tests work out of the box. get_settings() below
    # refuses to boot in production with this default (or anything shorter than
    # MIN_JWT_SECRET_LENGTH) -- see _validate_secrets and ARCHITECTURE.md's "Fail-fast
    # secret handling" section for why: this file is public, so the default value is
    # public too, and anyone who's read it can forge a valid session token against any
    # deployment that didn't override it.
    jwt_secret_key: str = INSECURE_DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 8
    # Refresh tokens are opaque, DB-stored, single-use (rotated on each refresh) --
    # see app.modules.auth.service.AuthService.refresh. This is just their lifetime.
    jwt_refresh_token_expire_days: int = 30

    # OIDC/Entra ID federation (see ARCHITECTURE.md's "Enterprise SSO" section). Off
    # by default; setting oidc_issuer turns it on as an *additional* auth path
    # alongside password login and API keys, not a replacement for them.
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    # Defaults to Entra ID's discovery convention (`{issuer}/discovery/v2.0/keys`) if
    # unset and oidc_issuer is a login.microsoftonline.com URL; any other OIDC
    # provider must set this explicitly (see get_oidc_jwks_url).
    oidc_jwks_url: str | None = None

    @property
    def oidc_enabled(self) -> bool:
        return self.oidc_issuer is not None

    def get_oidc_jwks_url(self) -> str | None:
        if self.oidc_jwks_url is not None:
            return self.oidc_jwks_url
        if self.oidc_issuer is None:
            return None
        return f"{self.oidc_issuer.rstrip('/')}/discovery/v2.0/keys"


def _validate_secrets(settings: Settings) -> None:
    """Refuses to construct usable settings in production with a missing, well-known,
    or too-short JWT secret. A standalone function (not a Settings validator) so it's
    directly unit-testable against constructed Settings instances without needing to
    manipulate process env vars/the get_settings() cache -- see
    tests/unit/core/test_config.py."""
    is_weak = (
        settings.jwt_secret_key == INSECURE_DEFAULT_JWT_SECRET
        or len(settings.jwt_secret_key) < MIN_JWT_SECRET_LENGTH
    )
    if not is_weak:
        return

    message = (
        "JWT_SECRET_KEY is missing, set to the well-known insecure default shipped in "
        "this open source repository, or shorter than "
        f"{MIN_JWT_SECRET_LENGTH} characters. Anyone who has read this repository's "
        "source knows the default value and can forge valid session tokens against any "
        "deployment that didn't override it. Set a real, random JWT_SECRET_KEY (e.g. "
        "`openssl rand -hex 32`) via the environment before starting this service."
    )
    if settings.environment == "production":
        raise RuntimeError(message)
    logger.warning(
        "%s (allowed to boot only because ENVIRONMENT=%r, not 'production')",
        message,
        settings.environment,
    )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    _validate_secrets(settings)
    return settings
