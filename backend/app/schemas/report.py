"""经营报表的出入参。

每张报表的**口径**都写在字段注释里 —— 报表最容易出的错不是算错，而是两边
对「及时率」「周转天数」的理解不一样。
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Granularity = Literal["day", "week", "month"]


# --------------------------------------------------------------- SKU 库存报表
class SkuStockRow(BaseModel):
    sku_id: int
    sku_code: str
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
    available_qty: int
    location_code: str = ""
    # 库存金额按采购价估算（不是销售价）
    stock_value_cents: int = 0


# --------------------------------------------------------------- 库存周转天数
class TurnoverRow(BaseModel):
    """周转天数 = 平均库存 / 日均销量。日均销量为 0 时视为无限（不周转）。"""

    sku_id: int
    sku_code: str
    sku_name: str = ""
    period_days: int
    sold_qty: int
    avg_daily_sales: float
    average_stock: float
    turnover_days: float | None = None  # None 表示窗口内无销量
    on_hand_qty: int = 0


# ---------------------------------------------------------- 供应商交付及时率
class SupplierOnTimeRow(BaseModel):
    """及时率 = 按期到货批次 / 总批次。到货日 <= 预计到货日即为按期。"""

    supplier_id: int
    supplier_name: str
    total_batches: int
    on_time_batches: int
    late_batches: int
    on_time_rate: float  # 0~1，没有批次时为 0
    avg_delay_days: float


# ---------------------------------------------------------------- 渠道销量
class ChannelSalesRow(BaseModel):
    bucket: str  # 聚合后的时间桶：2026-10-01 / 2026-W40 / 2026-10
    channel_id: int
    channel_code: str = ""
    channel_name: str = ""
    order_count: int
    item_quantity: int
    total_amount_cents: int


# ---------------------------------------------------------------- 缺货次数
class StockoutRow(BaseModel):
    sku_id: int
    sku_code: str
    sku_name: str = ""
    stockout_count: int
    shortage_qty: int = 0
    last_stockout_at: dt.datetime | None = None


# ------------------------------------------------------------------ 退货率
class ReturnRateRow(BaseModel):
    """退货率 = 退货数量 / 销售数量。分母为 0 时退货率为 0。"""

    sku_id: int
    sku_code: str
    sku_name: str = ""
    sold_qty: int
    returned_qty: int
    return_rate: float
    return_order_count: int = 0


# ------------------------------------------------------------------ 滞销
class SlowMovingRow(BaseModel):
    """近 N 天零出货且仍有库存。"""

    sku_id: int
    sku_code: str
    sku_name: str = ""
    warehouse_id: int
    warehouse_code: str = ""
    on_hand_qty: int
    stock_value_cents: int = 0
    idle_days: int


# -------------------------------------------------------------- 采购金额
class PurchaseAmountRow(BaseModel):
    bucket: str
    supplier_id: int
    supplier_name: str
    order_count: int
    total_amount_cents: int
    received_amount_cents: int = 0


# -------------------------------------------------------------- 盘点差异
class StocktakeVarianceRow(BaseModel):
    warehouse_id: int
    warehouse_code: str = ""
    warehouse_name: str = ""
    total_lines: int
    variance_lines: int
    gain_qty: int = 0   # 盘盈
    loss_qty: int = 0   # 盘亏
    net_qty: int = 0    # 净差异
    variance_amount_cents: int = 0


# ------------------------------------------------- 即将低于安全库存（M6 预警）
class LowStockRow(BaseModel):
    sku_id: int
    sku_code: str
    sku_name: str = ""
    warehouse_id: int
    warehouse_code: str = ""
    warehouse_name: str = ""
    available_qty: int
    in_transit_qty: int
    safety_qty: int
    gap_qty: int


# ------------------------------------------------------------ 经营看板汇总
class DashboardSummary(BaseModel):
    """看板顶部的几个关键数字。"""

    sku_count: int
    warehouse_count: int
    total_on_hand: int
    total_available: int
    total_stock_value_cents: int
    open_orders: int
    open_alerts: int
    open_exceptions: int
    pending_stocktakes: int
    period_days: int
    period_amount_cents: int = 0
    period_order_count: int = 0
    low_stock_count: int = 0
    supplier_count: int = 0


# ------------------------------------------------------------------ 审计日志
class AuditLogRead(BaseModel):
    id: int
    actor_id: int | None = None
    actor_name: str = ""
    action: str
    resource_type: str
    resource_id: str
    method: str
    path: str
    status_code: int
    ip: str
    user_agent: str
    request_id: str
    summary: str
    detail: dict = Field(default_factory=dict)
    created_at: dt.datetime | None = None


# -------------------------------------------------------------- 渠道适配器
class ChannelAdapterRead(BaseModel):
    id: int
    channel_id: int
    channel_code: str = ""
    channel_name: str = ""
    adapter_key: str
    enabled: bool
    config: dict
    sync_interval_minutes: int
    last_sync_at: dt.datetime | None = None
    last_sync_status: str
    last_sync_message: str
    remark: str
    created_at: dt.datetime | None = None


class ChannelAdapterIn(BaseModel):
    channel_id: int
    adapter_key: str = Field(min_length=1, max_length=48)
    enabled: bool = False
    config: dict = Field(default_factory=dict)
    sync_interval_minutes: int = Field(default=30, ge=1, le=10_080)
    remark: str = Field(default="", max_length=255)


class ChannelAdapterUpdate(BaseModel):
    adapter_key: str | None = Field(default=None, min_length=1, max_length=48)
    enabled: bool | None = None
    config: dict | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=1, le=10_080)
    remark: str | None = Field(default=None, max_length=255)


class AdapterSyncResult(BaseModel):
    adapter_key: str
    channel_id: int
    result: str  # created / duplicate / failed / skipped
    message: str
    created_orders: int = 0
    duplicate_orders: int = 0
    failed_rows: int = 0
    sync_log_id: int | None = None


class AdapterDescriptor(BaseModel):
    """适配器注册表里的一个可用适配器。"""

    key: str
    name: str
    kind: str  # file | api
    extensions: list[str] = Field(default_factory=list)
    description: str = ""
