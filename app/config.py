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
    database_url: str = Field(
        default="postgresql+psycopg://extract_to_act:extract_to_act@db:5432/extract_to_act",
        alias="DATABASE_URL",
    )

    # Phase 4 — see docs/adr/0008-api-authentication.md for why a shared
    # token is sufficient for now, and what it doesn't cover yet.
    api_key: str = Field(default="dev-only-not-for-production", alias="API_KEY")

    # Phase 4 — local disk in dev; S3-compatible in prod is a later phase
    # (STORAGE_BACKEND in .env.example documents that, not yet consumed).
    storage_local_dir: str = Field(default="/app/data/uploads", alias="STORAGE_LOCAL_DIR")
    max_upload_size_bytes: int = Field(default=20 * 1024 * 1024, alias="MAX_UPLOAD_SIZE_BYTES")


@lru_cache
def get_settings() -> Settings:
    return Settings()
