"""Supplier schemas."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class SupplierCreate(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    contact_name: str = Field(default="", max_length=64)
    contact_phone: str = Field(default="", max_length=32)
    email: str = Field(default="", max_length=128)
    address: str = Field(default="", max_length=255)
    payment_terms: str = Field(default="", max_length=64)
    lead_time_days: int = Field(default=7, ge=0, le=365)
    remark: str = Field(default="", max_length=255)


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    contact_name: str | None = Field(default=None, max_length=64)
    contact_phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=128)
    address: str | None = Field(default=None, max_length=255)
    payment_terms: str | None = Field(default=None, max_length=64)
    lead_time_days: int | None = Field(default=None, ge=0, le=365)
    is_active: bool | None = None
    remark: str | None = Field(default=None, max_length=255)


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    contact_name: str
    contact_phone: str
    email: str
    address: str
    payment_terms: str
    lead_time_days: int
    is_active: bool
    remark: str
    open_order_count: int = 0
    created_at: dt.datetime | None = None
