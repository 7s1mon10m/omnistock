"""Database engine and session management.

SQLite is the default so a small team can run OmniStock with zero external
services; pointing ``DATABASE_URL`` at a PostgreSQL DSN switches the same code
base over without any other change.  PostgreSQL is what production deployments
should use, because stock reservation relies on row level locks.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


def _engine_kwargs() -> dict[str, object]:
    if settings.DATABASE_URL.startswith("sqlite"):
        # FastAPI serves sync endpoints from a threadpool, so the connection
        # must be allowed to cross threads.  The timeout makes a concurrent
        # writer wait for the lock instead of failing immediately.
        return {"connect_args": {"check_same_thread": False, "timeout": 30}}
    return {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20}


engine = create_engine(
    settings.DATABASE_URL, echo=settings.SQL_ECHO, future=True, **_engine_kwargs()  # type: ignore[arg-type]
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create every table.

    Used by tests and by the seed script.  Real deployments run Alembic
    migrations instead so that schema changes stay versioned.
    """
    from app import models  # noqa: F401  (import registers every model)

    Base.metadata.create_all(bind=engine)


def dispose_engine() -> None:
    engine.dispose()
