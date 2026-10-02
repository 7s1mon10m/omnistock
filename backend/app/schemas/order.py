"""Order, import and exception schemas."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.models.order import (
    ExceptionStatus,
    ExceptionType,
    OrderSource,
    OrderStatus,
    SyncResult,
)


# ------------------------------------------------------------------ import in
class OrderItemIn(BaseModel):
    channel_product_code: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0, le=1_000_000)
    unit_price_cents: int = Field(default=0, ge=0)


class OrderIn(BaseModel):
    """One order as it arrives from a channel export."""

    # 允许为空：平台 API 的响应里通常没有「我们内部怎么称呼这个渠道」，
    # 渠道适配器同步时会用配置里的渠道编码补上。留空由导入流程给出明确报错，
    # 好过让适配器去猜一个 shop 名称把渠道映射做错。
    channel_code: str = Field(default="", max_length=32)
    shop_code: str | None = Field(default=None, max_length=32)
    channel_order_no: str = Field(min_length=1, max_length=64)
    buyer_nick: str = Field(default="", max_length=64)
    warehouse_code: str | None = Field(default=None, max_length=32)
    paid_at: dt.datetime | None = None
    remark: str = Field(default="", max_length=255)
    items: list[OrderItemIn] = Field(min_length=1)


class OrderImportRequest(BaseModel):
    """JSON import body.  CSV uploads use the same shape after parsing."""

    filename: str = Field(default="", max_length=255)
    source: OrderSource = OrderSource.IMPORT_JSON
    orders: list[OrderIn] = Field(min_length=1)


class ImportErrorRow(BaseModel):
    row: int
    code: int
    message: str
    channel_order_no: str = ""


class ImportResultRead(BaseModel):
    batch_id: int
    source: OrderSource
    total_rows: int
    created_orders: int
    duplicate_orders: int
    failed_rows: int
    reserved_orders: int
    exception_orders: int
    errors: list[ImportErrorRow] = Field(default_factory=list)


class ImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: OrderSource
    filename: str
    total_rows: int
    created_orders: int
    duplicate_orders: int
    failed_rows: int
    reserved_orders: int
    exception_orders: int
    created_at: dt.datetime | None = None


# ------------------------------------------------------------------ order out
class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    channel_product_code: str
    sku_id: int
    sku_code: str = ""
    sku_name: str = ""
    quantity: int
    unit_price_cents: int
    is_bundle: bool


class ReservationLine(BaseModel):
    """What is actually held in stock for this order, per component SKU."""

    sku_id: int
    sku_code: str
    warehouse_id: int
    warehouse_code: str
    quantity: int


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    channel_id: int
    channel_code: str = ""
    channel_name: str = ""
    shop_id: int | None = None
    shop_code: str = ""
    channel_order_no: str
    status: OrderStatus
    warehouse_id: int | None = None
    warehouse_code: str = ""
    buyer_nick: str
    total_amount_cents: int
    total_quantity: int = 0
    is_bundle: bool
    paid_at: dt.datetime | None = None
    source: OrderSource
    remark: str
    items: list[OrderItemRead] = Field(default_factory=list)
    reservations: list[ReservationLine] = Field(default_factory=list)
    open_exceptions: int = 0
    created_at: dt.datetime | None = None


class OrderListRead(BaseModel):
    """A lighter row for the order table."""

    id: int
    order_no: str
    channel_code: str = ""
    shop_code: str = ""
    channel_order_no: str
    status: OrderStatus
    buyer_nick: str
    total_amount_cents: int
    total_quantity: int = 0
    item_count: int = 0
    is_bundle: bool
    source: OrderSource
    created_at: dt.datetime | None = None


class MarkPaidRequest(BaseModel):
    paid_at: dt.datetime | None = None


class CancelOrderRequest(BaseModel):
    reason: str = Field(default="", max_length=255)


class OrderActionResult(BaseModel):
    """Returned by pay / cancel / retry-reserve."""

    order: OrderRead
    reserved: list[ReservationLine] = Field(default_factory=list)
    released: list[ReservationLine] = Field(default_factory=list)
    exceptions: list["OrderExceptionRead"] = Field(default_factory=list)
    message: str = ""


class OrderExceptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    order_no: str = ""
    channel_order_no: str = ""
    sku_id: int | None = None
    sku_code: str = ""
    sku_name: str = ""
    warehouse_code: str = ""
    type: ExceptionType
    status: ExceptionStatus
    required_qty: int
    available_qty: int
    shortage_qty: int = 0
    message: str
    created_at: dt.datetime | None = None


class SyncLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_id: int
    channel_code: str = ""
    shop_id: int | None = None
    channel_order_no: str
    order_id: int | None = None
    batch_id: int | None = None
    result: SyncResult
    message: str
    created_at: dt.datetime | None = None


OrderActionResult.model_rebuild()
