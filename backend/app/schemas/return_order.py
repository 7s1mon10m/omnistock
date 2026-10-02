"""退货单的出入参。"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.return_order import ReturnDisposition, ReturnReason, ReturnStatus


class ReturnItemIn(BaseModel):
    sku_id: int
    quantity: int = Field(gt=0, le=1_000_000)
    remark: str = Field(default="", max_length=255)


class ReturnOrderCreate(BaseModel):
    warehouse_id: int
    # 二选一：给 order_id 走系统内订单，给 channel_order_no 走平台单号
    order_id: int | None = None
    channel_order_no: str = Field(default="", max_length=64)
    channel_id: int | None = None
    buyer_nick: str = Field(default="", max_length=64)
    reason: ReturnReason = ReturnReason.OTHER
    remark: str = Field(default="", max_length=255)
    items: list[ReturnItemIn] = Field(min_length=1)


class ReturnItemInspect(BaseModel):
    """一行的质检结论。四个分流数量之和必须等于退货量。"""

    return_item_id: int
    disposition: ReturnDisposition
    resellable_qty: int = Field(default=0, ge=0)
    defective_qty: int = Field(default=0, ge=0)
    repair_qty: int = Field(default=0, ge=0)
    scrap_qty: int = Field(default=0, ge=0)
    remark: str = Field(default="", max_length=255)

    @model_validator(mode="after")
    def _check_total(self) -> "ReturnItemInspect":
        total = self.resellable_qty + self.defective_qty + self.repair_qty + self.scrap_qty
        if total <= 0:
            raise ValueError("至少要在一个分流上填数量")
        return self


class ReturnInspectRequest(BaseModel):
    items: list[ReturnItemInspect] = Field(min_length=1)
    remark: str = Field(default="", max_length=255)


class ReturnItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    sku_id: int
    sku_code: str = ""
    sku_name: str = ""
    quantity: int
    sold_qty: int
    returnable_qty: int = 0
    already_returned_qty: int = 0
    disposition: ReturnDisposition | None = None
    resellable_qty: int
    defective_qty: int
    repair_qty: int
    scrap_qty: int
    inspected_total: int = 0
    remark: str


class ReturnOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    return_no: str
    order_id: int | None = None
    channel_id: int | None = None
    channel_name: str = ""
    channel_order_no: str
    buyer_nick: str
    warehouse_id: int
    warehouse_code: str = ""
    warehouse_name: str = ""
    status: ReturnStatus
    reason: ReturnReason
    created_by: int | None = None
    created_by_name: str = ""
    inspected_by: int | None = None
    inspected_by_name: str = ""
    inspected_at: dt.datetime | None = None
    inbound_by: int | None = None
    inbound_by_name: str = ""
    inbound_at: dt.datetime | None = None
    total_quantity: int = 0
    remark: str
    items: list[ReturnItemRead] = Field(default_factory=list)
    created_at: dt.datetime | None = None


class ReturnOrderListRead(BaseModel):
    id: int
    return_no: str
    channel_order_no: str
    buyer_nick: str
    warehouse_name: str = ""
    status: ReturnStatus
    reason: ReturnReason
    total_quantity: int = 0
    created_at: dt.datetime | None = None


class ReturnCancelRequest(BaseModel):
    reason: str = Field(default="", max_length=255)


ReturnOrderRead.model_rebuild()
