"""库存预警与补货建议的出入参。"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.models.alert import AlertRuleScope, AlertStatus, AlertType, SuggestionStatus


# ------------------------------------------------------------------- alert rule
class AlertRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: AlertRuleScope = AlertRuleScope.GLOBAL
    spu_id: int | None = None
    sku_id: int | None = None
    warehouse_id: int | None = None
    threshold_qty: int | None = Field(default=None, ge=0, le=10_000_000)
    enabled: bool = True
    notify_channels: str = Field(default="", max_length=120)
    remark: str = Field(default="", max_length=255)


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    threshold_qty: int | None = Field(default=None, ge=0, le=10_000_000)
    enabled: bool | None = None
    notify_channels: str | None = Field(default=None, max_length=120)
    remark: str | None = Field(default=None, max_length=255)


class AlertRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    scope: AlertRuleScope
    spu_id: int | None = None
    spu_name: str = ""
    sku_id: int | None = None
    sku_code: str = ""
    warehouse_id: int | None = None
    warehouse_name: str = ""
    threshold_qty: int | None = None
    enabled: bool
    notify_channels: str
    remark: str
    created_at: dt.datetime | None = None


# ------------------------------------------------------------------------ alert
class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_no: str
    type: AlertType
    status: AlertStatus
    rule_id: int | None = None
    sku_id: int
    sku_code: str = ""
    sku_name: str = ""
    warehouse_id: int
    warehouse_code: str = ""
    warehouse_name: str = ""
    available_qty: int
    in_transit_qty: int
    safety_qty: int
    gap_qty: int
    message: str
    detected_at: dt.datetime | None = None
    acknowledged_by: int | None = None
    acknowledged_by_name: str = ""
    acknowledged_at: dt.datetime | None = None
    resolved_at: dt.datetime | None = None
    created_at: dt.datetime | None = None


class AckAlertRequest(BaseModel):
    remark: str = Field(default="", max_length=255)


# ------------------------------------------------------------------- suggestion
class SuggestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    suggestion_no: str
    sku_id: int
    sku_code: str = ""
    sku_name: str = ""
    warehouse_id: int
    warehouse_code: str = ""
    warehouse_name: str = ""
    supplier_id: int | None = None
    supplier_name: str = ""
    avg_daily_sales: float
    forecast_qty: int
    safety_qty: int
    available_qty: int
    in_transit_qty: int
    suggested_qty: int
    status: SuggestionStatus
    purchase_order_id: int | None = None
    generated_at: dt.datetime | None = None
    converted_at: dt.datetime | None = None
    remark: str
    created_at: dt.datetime | None = None


class SuggestionToPurchaseOrder(BaseModel):
    """把建议转成采购单；大部分字段留空即采用建议里的值。"""

    supplier_id: int | None = None
    warehouse_id: int | None = None
    quantity: int | None = Field(default=None, gt=0, le=10_000_000)
    unit_price_cents: int = Field(default=0, ge=0)
    remark: str = Field(default="", max_length=255)


class ScanResult(BaseModel):
    """一次扫描的结果摘要。"""

    scanned: int = 0
    alerts_created: int = 0
    alerts_skipped: int = 0
    resolved: int = 0
    suggestions_created: int = 0
    notifications_sent: int = 0
