"""库存预警与补货建议。

两个概念分开是有意的：

* ``AlertRule`` 是**规则** —— 谁在什么范围内按什么阈值盯着；
* ``Alert`` 是**一次命中** —— 某个 SKU 在某个仓库真的低于安全库存了。

把「规则」和「命中」混成一张表，就没法在不清空告警历史的前提下调整阈值。
"""

from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, enum_type, utcnow
from app.models.product import Sku, Spu
from app.models.supplier import Supplier
from app.models.user import User
from app.models.warehouse import Warehouse


class AlertRuleScope(str, Enum):
    """规则生效的范围。范围越窄优先级越高（sku > warehouse > category > global）。"""

    GLOBAL = "global"          # 全局默认
    CATEGORY = "category"      # 某个 SPU（品类）
    SKU = "sku"                # 单个 SKU
    WAREHOUSE = "warehouse"    # 某个仓库内的全部 SKU


class AlertType(str, Enum):
    """命中类型。``out_of_stock`` 比 ``low_stock`` 更严重。"""

    LOW_STOCK = "low_stock"        # 可售 + 在途 < 安全库存
    OUT_OF_STOCK = "out_of_stock"  # 可售 + 在途 == 0


class AlertStatus(str, Enum):
    OPEN = "open"        # 待处理
    ACKED = "acked"      # 已知悉，等补货
    RESOLVED = "resolved"  # 已解决（补货到位或人工关闭）


class SuggestionStatus(str, Enum):
    OPEN = "open"            # 待转采购单
    CONVERTED = "converted"  # 已转成采购单
    DISMISSED = "dismissed"  # 人工忽略


class AlertRule(Base, TimestampMixin):
    """一条安全库存规则。``threshold_qty`` 为空时表示沿用 SKU 自身的安全库存。"""

    __tablename__ = "alert_rules"
    __table_args__ = (
        # 含 NULL 的组合在 SQLite / PostgreSQL 上都不强制唯一，所以「同一范围
        # 只能有一条规则」由服务层校验；这个索引主要负责挡住完全重复的写法。
        UniqueConstraint(
            "scope", "spu_id", "sku_id", "warehouse_id", name="uq_alert_rule_target"
        ),
        Index("ix_alert_rules_enabled", "enabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    scope: Mapped[AlertRuleScope] = mapped_column(
        enum_type(AlertRuleScope, "alert_rule_scope"), default=AlertRuleScope.GLOBAL, nullable=False
    )

    spu_id: Mapped[int | None] = mapped_column(
        ForeignKey("spus.id", ondelete="CASCADE"), default=None, nullable=True
    )
    sku_id: Mapped[int | None] = mapped_column(
        ForeignKey("skus.id", ondelete="CASCADE"), default=None, nullable=True
    )
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouses.id", ondelete="CASCADE"), default=None, nullable=True
    )

    # 覆盖 SKU 自带的安全库存；为空则沿用 inventory_stocks.safety_qty。
    threshold_qty: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 逗号分隔的通道覆盖（inapp,email,webhook）；为空则用系统默认。
    notify_channels: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    spu: Mapped[Spu | None] = relationship(lazy="selectin")
    sku: Mapped[Sku | None] = relationship(lazy="selectin")
    warehouse: Mapped[Warehouse | None] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<AlertRule {self.scope} name={self.name!r} threshold={self.threshold_qty}>"


class Alert(Base, TimestampMixin):
    """一次低库存命中。

    ``dedup_key`` 是防重复告警的关键：只要还有一条未解决的同类告警占着这个
    键，扫描任务就不会再生成第二条。告警被 resolve 时把键清空，下一次低于
    阈值时才能重新告警 —— 否则同一件事会被永远静音。
    """

    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("alert_no", name="uq_alerts_no"),
        UniqueConstraint("dedup_key", name="uq_alerts_dedup"),
        Index("ix_alerts_status_type", "status", "type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_no: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    type: Mapped[AlertType] = mapped_column(
        enum_type(AlertType, "alert_type"), nullable=False
    )
    status: Mapped[AlertStatus] = mapped_column(
        enum_type(AlertStatus, "alert_status"), default=AlertStatus.OPEN, nullable=False
    )

    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="SET NULL"), default=None, nullable=True
    )
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="CASCADE"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False
    )

    # 命中时的口径快照，方便事后复盘「当时为什么告警」。
    available_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    in_transit_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    safety_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 缺口 = 安全库存 - (可售 + 在途)，恒为正。
    gap_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    message: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    acknowledged_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, default=None, nullable=True
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    # 未解决时占用；解决后清空，允许同一目标再次告警。
    dedup_key: Mapped[str | None] = mapped_column(String(96), default=None, nullable=True)

    rule: Mapped[AlertRule | None] = relationship(lazy="selectin")
    sku: Mapped[Sku] = relationship(lazy="selectin")
    warehouse: Mapped[Warehouse] = relationship(lazy="selectin")
    acknowledged_by_user: Mapped[User | None] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Alert {self.alert_no} {self.type} sku={self.sku_id} wh={self.warehouse_id}>"


class ReplenishmentSuggestion(Base, TimestampMixin):
    """一条补货建议：建议采购量 = 预测销量 + 安全库存 - 可售 - 在途。"""

    __tablename__ = "replenishment_suggestions"
    __table_args__ = (
        UniqueConstraint("suggestion_no", name="uq_replenishment_no"),
        UniqueConstraint("dedup_key", name="uq_replenishment_dedup"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    suggestion_no: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="CASCADE"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), default=None, nullable=True
    )

    # 公式的四个输入 + 结论，全部落库，方便解释「为什么建议买这么多」。
    avg_daily_sales: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    forecast_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    safety_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    in_transit_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    suggested_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[SuggestionStatus] = mapped_column(
        enum_type(SuggestionStatus, "suggestion_status"),
        default=SuggestionStatus.OPEN,
        nullable=False,
    )
    purchase_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="SET NULL"), default=None, nullable=True
    )
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    converted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(96), default=None, nullable=True)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    sku: Mapped[Sku] = relationship(lazy="selectin")
    warehouse: Mapped[Warehouse] = relationship(lazy="selectin")
    supplier: Mapped[Supplier | None] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Suggestion {self.suggestion_no} sku={self.sku_id} qty={self.suggested_qty}>"
