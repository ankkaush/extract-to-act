"""Application configuration, loaded from environment variables.

Only variables actually consumed by code that exists yet are declared here.
Variables for features from later phases (extraction providers, storage,
accounting adapters, ...) live in `.env.example` as documentation of what's
coming, but are deliberately not referenced here until their owning phase
wires them up — see PLAN.md.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")
    app_secret_key: str = Field(default="dev-only-not-for-production", alias="APP_SECRET_KEY")


@lru_cache
def get_settings() -> Settings:
    return Settings()
