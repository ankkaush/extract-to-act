"""Tier 1 (docs/testing-strategy.md): pure Settings field validators, no
I/O, no DB session, no real environment.
"""

from app.config import Settings


def test_bare_postgresql_scheme_is_normalized_to_psycopg_driver():
    settings = Settings(DATABASE_URL="postgresql://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+psycopg://user:pass@host:5432/db"


def test_already_correct_scheme_is_left_unchanged():
    settings = Settings(DATABASE_URL="postgresql+psycopg://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+psycopg://user:pass@host:5432/db"


def test_default_database_url_already_has_the_right_scheme():
    settings = Settings()
    assert settings.database_url.startswith("postgresql+psycopg://")
