"""Warehouse and location schemas."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.models.warehouse import WarehouseType


class LocationCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(default="", max_length=64)
    zone: str = Field(default="", max_length=64)
    is_active: bool = True


class LocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    warehouse_id: int
    code: str
    name: str
    zone: str
    is_active: bool


class WarehouseCreate(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    type: WarehouseType = WarehouseType.MAIN
    address: str = Field(default="", max_length=255)
    contact_name: str = Field(default="", max_length=64)
    contact_phone: str = Field(default="", max_length=32)
    remark: str = Field(default="", max_length=255)


class WarehouseUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    type: WarehouseType | None = None
    address: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=64)
    contact_phone: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None
    remark: str | None = Field(default=None, max_length=255)


class WarehouseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    type: WarehouseType
    address: str
    contact_name: str
    contact_phone: str
    is_active: bool
    remark: str
    location_count: int = 0
    created_at: dt.datetime | None = None
