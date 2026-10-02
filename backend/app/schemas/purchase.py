"""Purchase order and goods receipt schemas."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.purchase import PurchaseOrderStatus, ReceiptStatus


# ------------------------------------------------------------- purchase order
class PurchaseOrderItemIn(BaseModel):
    sku_id: int
    quantity: int = Field(gt=0, le=1_000_000)
    unit_price_cents: int = Field(default=0, ge=0)
    remark: str = Field(default="", max_length=255)


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    warehouse_id: int
    expected_at: dt.datetime | None = None
    remark: str = Field(default="", max_length=255)
    items: list[PurchaseOrderItemIn] = Field(min_length=1)


class PurchaseOrderUpdate(BaseModel):
    """Only a draft may be edited."""

    expected_at: dt.datetime | None = None
    remark: str | None = Field(default=None, max_length=255)
    items: list[PurchaseOrderItemIn] | None = None


class PurchaseItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    sku_id: int
    sku_code: str = ""
    sku_name: str = ""
    quantity: int
    received_qty: int
    defective_qty: int
    outstanding_qty: int = 0
    unit_price_cents: int
    remark: str


class PurchaseOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    po_no: str
    supplier_id: int
    supplier_code: str = ""
    supplier_name: str = ""
    warehouse_id: int
    warehouse_code: str = ""
    warehouse_name: str = ""
    status: PurchaseOrderStatus
    ordered_at: dt.datetime | None = None
    expected_at: dt.datetime | None = None
    total_amount_cents: int
    total_quantity: int = 0
    received_quantity: int = 0
    is_fully_received: bool = False
    buyer_id: int | None = None
    buyer_name: str = ""
    remark: str
    items: list[PurchaseItemRead] = Field(default_factory=list)
    receipts: list["ReceiptBrief"] = Field(default_factory=list)
    created_at: dt.datetime | None = None


class PurchaseOrderListRead(BaseModel):
    id: int
    po_no: str
    supplier_name: str = ""
    warehouse_code: str = ""
    status: PurchaseOrderStatus
    total_quantity: int = 0
    received_quantity: int = 0
    total_amount_cents: int
    expected_at: dt.datetime | None = None
    created_at: dt.datetime | None = None


# -------------------------------------------------------------------- receipt
class ReceiptItemIn(BaseModel):
    order_item_id: int
    # 本次到货总量；其中 defective_qty 进次品区，其余进可售
    quantity: int = Field(gt=0, le=1_000_000)
    defective_qty: int = Field(default=0, ge=0)
    location_id: int | None = None
    remark: str = Field(default="", max_length=255)

    @model_validator(mode="after")
    def _defective_within_quantity(self) -> "ReceiptItemIn":
        if self.defective_qty > self.quantity:
            raise ValueError("次品数量不能多于到货数量")
        return self


class ReceiptCreate(BaseModel):
    items: list[ReceiptItemIn] = Field(min_length=1)
    remark: str = Field(default="", max_length=255)
    # 防止重复提交同一张收货单
    idempotency_key: str | None = Field(default=None, max_length=64)


class ReceiptItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_item_id: int
    sku_id: int
    sku_code: str = ""
    sku_name: str = ""
    quantity: int
    defective_qty: int
    qualified_qty: int = 0
    location_id: int | None = None
    location_code: str = ""
    remark: str


class ReceiptBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    receipt_no: str
    status: ReceiptStatus
    total_quantity: int = 0
    total_defective: int = 0
    received_at: dt.datetime | None = None


class ReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    receipt_no: str
    order_id: int
    po_no: str = ""
    warehouse_id: int
    warehouse_code: str = ""
    status: ReceiptStatus
    received_by: int | None = None
    received_by_name: str = ""
    received_at: dt.datetime | None = None
    total_quantity: int = 0
    total_defective: int = 0
    remark: str
    items: list[ReceiptItemRead] = Field(default_factory=list)
    created_at: dt.datetime | None = None


class ReceiptResult(BaseModel):
    receipt: ReceiptRead
    order: PurchaseOrderRead
    message: str = ""


PurchaseOrderRead.model_rebuild()
