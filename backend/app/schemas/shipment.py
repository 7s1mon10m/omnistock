"""Shipment / picking schemas."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.models.shipment import PickResult, ShipmentItemStatus, ShipmentStatus


# --------------------------------------------------------------- create / read
class ShipmentCreate(BaseModel):
    order_id: int
    remark: str = Field(default="", max_length=255)


class ShipmentItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    sku_id: int
    sku_code: str = ""
    sku_name: str = ""
    barcode: str = ""
    location_id: int | None = None
    location_code: str = ""
    location_name: str = ""
    quantity: int
    picked_qty: int
    status: ShipmentItemStatus
    is_bundle_component: bool = False
    remark: str


class ShipmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipment_no: str
    order_id: int
    order_no: str = ""
    channel_code: str = ""
    channel_order_no: str = ""
    buyer_nick: str = ""
    warehouse_id: int
    warehouse_code: str = ""
    warehouse_name: str = ""
    status: ShipmentStatus
    picker_id: int | None = None
    picker_name: str = ""
    picked_at: dt.datetime | None = None
    packed_by: int | None = None
    packed_by_name: str = ""
    packed_at: dt.datetime | None = None
    package_count: int
    weight_g: int
    carrier: str
    tracking_no: str
    shipped_at: dt.datetime | None = None
    remark: str
    total_quantity: int = 0
    picked_quantity: int = 0
    is_fully_picked: bool = False
    items: list[ShipmentItemRead] = Field(default_factory=list)
    created_at: dt.datetime | None = None


class ShipmentListRead(BaseModel):
    id: int
    shipment_no: str
    order_no: str = ""
    channel_code: str = ""
    channel_order_no: str = ""
    buyer_nick: str = ""
    warehouse_code: str = ""
    status: ShipmentStatus
    picker_name: str = ""
    total_quantity: int = 0
    picked_quantity: int = 0
    carrier: str = ""
    tracking_no: str = ""
    created_at: dt.datetime | None = None


# --------------------------------------------------------------------- actions
class ClaimRequest(BaseModel):
    """Optionally hand the job to a specific picker; defaults to the caller."""

    picker_id: int | None = None


class PickRequest(BaseModel):
    """A scan. ``quantity`` defaults to one unit per scan."""

    barcode: str = Field(min_length=1, max_length=64)
    quantity: int = Field(default=1, gt=0, le=10_000)


class PickManualRequest(BaseModel):
    """Confirm a line without a barcode (paper-pick warehouses)."""

    shipment_item_id: int
    quantity: int = Field(gt=0, le=10_000)


class PickResultRead(BaseModel):
    accepted: bool
    result: PickResult
    message: str
    shipment_id: int
    shipment_item_id: int | None = None
    sku_id: int | None = None
    sku_code: str = ""
    picked_qty: int = 0
    quantity: int = 0
    shipment_status: ShipmentStatus
    progress: str = ""


class PackRequest(BaseModel):
    package_count: int = Field(default=1, gt=0, le=1_000)
    weight_g: int = Field(default=0, ge=0)
    remark: str = Field(default="", max_length=255)


class ShipRequest(BaseModel):
    carrier: str = Field(default="", max_length=64)
    tracking_no: str = Field(default="", max_length=64)
    remark: str = Field(default="", max_length=255)


class CancelShipmentRequest(BaseModel):
    reason: str = Field(default="", max_length=255)


class ShipmentActionResult(BaseModel):
    shipment: ShipmentRead
    message: str = ""
    #: Ledger rows written by an outbound, for the UI to show what left the shelf.
    outbound: list["OutboundLine"] = Field(default_factory=list)


class OutboundLine(BaseModel):
    sku_id: int
    sku_code: str
    warehouse_code: str
    quantity: int


# ------------------------------------------------------------------ pick log
class PickRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipment_id: int
    shipment_item_id: int | None = None
    barcode: str
    quantity: int
    result: PickResult
    accepted: bool
    message: str
    sku_id: int | None = None
    sku_code: str = ""
    operator_id: int | None = None
    operator_name: str = ""
    created_at: dt.datetime | None = None


ShipmentActionResult.model_rebuild()
