"""Engine/session setup. Not wired into any route yet — that starts in
Phase 4. Exists in Phase 3 so Alembic and tests have something to target.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def get_engine():
    return create_engine(get_settings().database_url, future=True)


SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
