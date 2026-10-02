"""Stock transfer schemas."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.transfer import TransferStatus


class TransferItemIn(BaseModel):
    sku_id: int
    quantity: int = Field(gt=0, le=1_000_000)
    remark: str = Field(default="", max_length=255)


class TransferCreate(BaseModel):
    from_warehouse_id: int
    to_warehouse_id: int
    reason: str = Field(default="", max_length=255)
    remark: str = Field(default="", max_length=255)
    items: list[TransferItemIn] = Field(min_length=1)

    @model_validator(mode="after")
    def _different_warehouses(self) -> "TransferCreate":
        if self.from_warehouse_id == self.to_warehouse_id:
            raise ValueError("调出仓与调入仓不能相同")
        return self


class TransferItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    sku_id: int
    sku_code: str = ""
    sku_name: str = ""
    quantity: int
    shipped_qty: int
    received_qty: int
    defective_qty: int
    qualified_qty: int = 0
    remark: str


class TransferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transfer_no: str
    from_warehouse_id: int
    from_warehouse_code: str = ""
    from_warehouse_name: str = ""
    to_warehouse_id: int
    to_warehouse_code: str = ""
    to_warehouse_name: str = ""
    status: TransferStatus
    reason: str
    remark: str
    requested_by: int | None = None
    requested_by_name: str = ""
    requested_at: dt.datetime | None = None
    approved_by: int | None = None
    approved_by_name: str = ""
    approved_at: dt.datetime | None = None
    reject_reason: str
    shipped_by: int | None = None
    shipped_by_name: str = ""
    shipped_at: dt.datetime | None = None
    received_by: int | None = None
    received_by_name: str = ""
    received_at: dt.datetime | None = None
    total_quantity: int = 0
    shipped_quantity: int = 0
    received_quantity: int = 0
    items: list[TransferItemRead] = Field(default_factory=list)
    created_at: dt.datetime | None = None


class TransferListRead(BaseModel):
    id: int
    transfer_no: str
    from_warehouse_code: str = ""
    to_warehouse_code: str = ""
    status: TransferStatus
    reason: str
    total_quantity: int = 0
    shipped_quantity: int = 0
    received_quantity: int = 0
    created_at: dt.datetime | None = None


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=255)


class ShipItemIn(BaseModel):
    transfer_item_id: int
    # 允许少发（例如货不够）；缺省表示按申请量发
    quantity: int | None = Field(default=None, gt=0, le=1_000_000)


class TransferShipRequest(BaseModel):
    items: list[ShipItemIn] | None = None
    remark: str = Field(default="", max_length=255)


class ReceiveItemIn(BaseModel):
    transfer_item_id: int
    # 实收总量；其中 defective_qty 进次品区
    quantity: int | None = Field(default=None, gt=0, le=1_000_000)
    defective_qty: int = Field(default=0, ge=0)


class TransferReceiveRequest(BaseModel):
    items: list[ReceiveItemIn] | None = None
    remark: str = Field(default="", max_length=255)


class CancelTransferRequest(BaseModel):
    reason: str = Field(default="", max_length=255)


TransferRead.model_rebuild()
