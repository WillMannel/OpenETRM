"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "OpenETRM"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://openetrm:openetrm@localhost:5432/openetrm"
    redis_url: str = "redis://localhost:6379/0"

    # v1's pilot commodity; Commodity.WTI exists too, to prove the enum isn't hardcoded.
    pilot_commodity: str = "HENRY_HUB"

    # Flat risk-free rate used to discount option cash flows (Black-76). No real yield
    # curve in v1 -- see ARCHITECTURE.md.
    risk_free_rate: float = 0.05

    log_level: str = "INFO"

    # Auth. jwt_secret_key MUST be overridden via env var in any real deployment --
    # the default here is only so local dev/tests work out of the box.
    jwt_secret_key: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
