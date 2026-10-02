"""盘点单的出入参。"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.models.stocktake import StocktakeStatus


class StocktakeCreate(BaseModel):
    warehouse_id: int
    scope: str = Field(default="全部", max_length=120)
    remark: str = Field(default="", max_length=255)
    # 为空表示把该仓所有 SKU 都列入盘点半
    sku_ids: list[int] | None = None


class StocktakeCountItem(BaseModel):
    stocktake_item_id: int
    counted_qty: int = Field(ge=0, le=10_000_000)
    reason: str = Field(default="", max_length=255)


class StocktakeCountRequest(BaseModel):
    """批量录入实盘数。也支持扫码逐条提交。"""

    items: list[StocktakeCountItem] = Field(min_length=1)


class StocktakeScanRequest(BaseModel):
    """扫码录入：只给条码与实盘数，系统自己找对应行。"""

    barcode: str = Field(min_length=1, max_length=64)
    counted_qty: int = Field(ge=0, le=10_000_000)


class StocktakeLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    sku_id: int
    sku_code: str = ""
    sku_name: str = ""
    barcode: str = ""
    book_qty: int
    counted_qty: int | None = None
    variance_qty: int = 0
    counted_by_name: str = ""
    counted_at: dt.datetime | None = None
    reason: str
    adjusted: bool
    remark: str


class StocktakeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stocktake_no: str
    warehouse_id: int
    warehouse_code: str = ""
    warehouse_name: str = ""
    status: StocktakeStatus
    scope: str
    created_by: int | None = None
    created_by_name: str = ""
    submitted_by: int | None = None
    submitted_by_name: str = ""
    submitted_at: dt.datetime | None = None
    approved_by: int | None = None
    approved_by_name: str = ""
    approved_at: dt.datetime | None = None
    remark: str
    total_lines: int = 0
    counted_lines: int = 0
    variance_lines: int = 0
    total_variance: int = 0
    max_abs_variance: int = 0
    items: list[StocktakeLineRead] = Field(default_factory=list)
    created_at: dt.datetime | None = None


class StocktakeListRead(BaseModel):
    id: int
    stocktake_no: str
    warehouse_name: str = ""
    status: StocktakeStatus
    scope: str
    total_lines: int = 0
    counted_lines: int = 0
    variance_lines: int = 0
    total_variance: int = 0
    created_at: dt.datetime | None = None


class StocktakeApproveRequest(BaseModel):
    remark: str = Field(default="", max_length=255)


StocktakeRead.model_rebuild()
