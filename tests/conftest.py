"""Shared fixtures for tests that need a real database.

These are not Tier 3/4 "real provider" tests in the docs/testing-strategy.md
sense — Postgres is free and local, not a paid external API. They do need
DATABASE_URL pointing at a reachable Postgres (the docker-compose `db`
service, or CI's postgres service container).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(get_settings().database_url, future=True)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection, future=True)
    session: Session = session_factory()
    try:
        yield session
    finally:
        session.close()
        # A test that triggers an IntegrityError (e.g. a uniqueness or FK
        # violation) already invalidates this transaction as a side effect
        # of the failed flush — rolling back again would just warn.
        if transaction.is_active:
            transaction.rollback()
        connection.close()
