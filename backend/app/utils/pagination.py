"""Pagination helpers shared by every list endpoint."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class PageResult:
    items: list
    total: int
    page: int
    page_size: int


DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200


def normalize_page(page: int, page_size: int) -> tuple[int, int]:
    page = max(1, page)
    page_size = min(max(1, page_size), MAX_PAGE_SIZE)
    return page, page_size


def paginate(session: Session, stmt: Select, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> PageResult:
    """Run ``stmt`` twice: once for the slice, once for the total count."""
    page, page_size = normalize_page(page, page_size)
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = list(session.scalars(stmt.limit(page_size).offset((page - 1) * page_size)).all())
    return PageResult(items=items, total=total, page=page, page_size=page_size)
