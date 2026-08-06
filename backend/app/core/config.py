"""Application settings, loaded from environment variables (see .env.example)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "OpenETRM"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://openetrm:openetrm@localhost:5432/openetrm"
    redis_url: str = "redis://localhost:6379/0"

    # v1 is deliberately single-commodity; this is the only value in use today.
    pilot_commodity: str = "HENRY_HUB"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
