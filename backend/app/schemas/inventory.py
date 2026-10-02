"""Inventory schemas."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.models.inventory import InventoryTransactionType


class InventoryStockRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku_id: int
    sku_code: str = ""
    sku_name: str = ""
    warehouse_id: int
    warehouse_code: str = ""
    warehouse_name: str = ""

    on_hand_qty: int
    reserved_qty: int
    in_transit_qty: int
    safety_qty: int
    defective_qty: int
    repair_qty: int
    # Derived server-side so every client shows the same number.
    available_qty: int
    version: int
    updated_at: dt.datetime | None = None


class InventoryAdjustRequest(BaseModel):
    sku_id: int
    warehouse_id: int
    # Signed: +5 adds five units, -3 removes three.
    qty_delta: int
    reason: str = Field(min_length=1, max_length=255)
    location_id: int | None = None
    # Optional client-supplied guard against duplicate submissions.
    idempotency_key: str | None = Field(default=None, max_length=64)


class InventoryReserveRequest(BaseModel):
    sku_id: int
    warehouse_id: int
    quantity: int = Field(gt=0, le=1_000_000)
    ref_type: str = Field(default="manual", max_length=32)
    ref_id: int | None = None
    remark: str = Field(default="", max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=64)


class BundleReserveRequest(BaseModel):
    """Reserve a bundle: it is exploded into component SKUs server-side."""

    bundle_sku_id: int
    warehouse_id: int
    quantity: int = Field(gt=0, le=100_000)
    ref_type: str = Field(default="manual", max_length=32)
    ref_id: int | None = None
    idempotency_key: str | None = Field(default=None, max_length=64)


class InventoryTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku_id: int
    sku_code: str = ""
    warehouse_id: int
    warehouse_code: str = ""
    location_id: int | None
    type: InventoryTransactionType
    qty_delta: int
    on_hand_before: int
    on_hand_after: int
    reserved_before: int
    reserved_after: int
    ref_type: str
    ref_id: int | None
    operator_id: int | None
    operator_name: str = ""
    remark: str
    created_at: dt.datetime
