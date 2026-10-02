"""Envelopes shared by many endpoints."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class OkResponse(BaseModel):
    ok: bool = True
    message: str = ""


class Page(BaseModel, Generic[T]):
    """A page of results plus the metadata a table needs."""

    model_config = ConfigDict(from_attributes=True)

    items: list[T]
    total: int
    page: int
    page_size: int
