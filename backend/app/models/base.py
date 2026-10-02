"""Shared column mixins for every ORM model."""

from __future__ import annotations

import datetime as dt
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> dt.datetime:
    """Naive UTC timestamp.

    Stored timestamps are naive UTC so that SQLite and PostgreSQL behave
    identically; the API layer converts to the caller's timezone when needed.
    """
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def enum_type(enum_cls: type[PyEnum], name: str) -> SAEnum:
    """An ``Enum`` column that stores the member *value*, not its name.

    SQLAlchemy stores member names by default, which would put ``ORDER_RESERVE``
    in the database.  Persisting the lower-case value (``order_reserve``) keeps
    raw SQL, reports and CSV exports readable.
    """
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class SoftDeleteMixin:
    """Records are never physically removed, only flagged."""

    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
