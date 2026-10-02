"""Inventory: the aggregate per SKU x warehouse, and the append-only ledger.

The ledger is the single source of truth.  ``InventoryStock`` is only a
materialised aggregate of it; nothing may change a stock number without writing
a matching ``InventoryTransaction`` row.
"""

from __future__ import annotations

from enum import Enum

from sqlalchemy import (
        ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, enum_type
from app.models.product import Sku
from app.models.user import User
from app.models.warehouse import Warehouse, WarehouseLocation


class InventoryTransactionType(str, Enum):
    """Every reason stock may move.  Once written, a row is never edited."""

    PURCHASE_INBOUND = "purchase_inbound"    # 采购入库
    ORDER_RESERVE = "order_reserve"          # 订单占用
    ORDER_RELEASE = "order_release"          # 订单取消释放
    ORDER_OUTBOUND = "order_outbound"        # 拣货出库
    RETURN_INBOUND = "return_inbound"        # 退货入库（可再售）
    RETURN_DEFECTIVE = "return_defective"    # 退货次品入库
    RETURN_REPAIR = "return_repair"          # 退货维修入库
    DAMAGE_SCRAP = "damage_scrap"            # 报损
    TRANSFER_OUT = "transfer_out"            # 调拨出库
    TRANSFER_IN = "transfer_in"              # 调拨入库
    STOCKTAKE_ADJUST = "stocktake_adjust"    # 盘点调整
    MANUAL_ADJUST = "manual_adjust"          # 手工调整


class InventoryStock(Base, TimestampMixin):
    """Aggregated stock for one SKU in one warehouse.

    ``available`` is never stored: it is derived so the three inputs can never
    drift apart.  See :func:`app.domain.stock_formula.available_qty`.
    """

    __tablename__ = "inventory_stocks"
    __table_args__ = (UniqueConstraint("sku_id", "warehouse_id", name="uq_stock_sku_warehouse"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="CASCADE"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False
    )

    on_hand_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)      # 实际库存
    reserved_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)    # 已占用
    in_transit_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 在途
    safety_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)      # 安全库存
    defective_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)   # 次品
    repair_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)      # 维修

    # Optimistic-lock version, bumped on every write.
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    sku: Mapped[Sku] = relationship(lazy="selectin")
    warehouse: Mapped[Warehouse] = relationship(lazy="selectin")

    @property
    def available_qty(self) -> int:
        """可售库存 = 实际 - 已占用 - 安全。"""
        return self.on_hand_qty - self.reserved_qty - self.safety_qty

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<InventoryStock sku={self.sku_id} wh={self.warehouse_id} on_hand={self.on_hand_qty}>"


class InventoryTransaction(Base, TimestampMixin):
    """One immutable stock movement.

    Carries the before/after snapshot so a discrepancy can be traced back
    without replaying the whole history.
    """

    __tablename__ = "inventory_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="CASCADE"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False
    )
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouse_locations.id", ondelete="SET NULL"), default=None, nullable=True
    )

    type: Mapped[InventoryTransactionType] = mapped_column(
        enum_type(InventoryTransactionType, "inventory_tx_type"), nullable=False
    )
    # Signed change; positive means stock went up.
    qty_delta: Mapped[int] = mapped_column(Integer, nullable=False)

    on_hand_before: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    on_hand_after: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_before: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_after: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Source document, e.g. ("sales_order", 42) or ("manual", None).
    ref_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    ref_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True)

    operator_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    # Guards against a duplicated message booking the same movement twice.
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True, unique=True
    )
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    sku: Mapped[Sku] = relationship(lazy="selectin")
    warehouse: Mapped[Warehouse] = relationship(lazy="selectin")
    location: Mapped[WarehouseLocation | None] = relationship(lazy="selectin")
    operator: Mapped[User | None] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<InventoryTx {self.type} sku={self.sku_id} delta={self.qty_delta}>"
