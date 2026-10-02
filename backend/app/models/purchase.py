"""Purchase orders and goods receipts.

The point of this module is that stock only ever appears after a **receipt**, and
a receipt always splits what arrived into qualified goods and defectives.  A
purchase order on its own changes nothing — it is a promise, not inventory.

分批到货是正常情况，不是异常：一张采购单可以对应多张收货单，每张只收一部分。
状态机::

    draft ──submit──▶ submitted ──部分到货──▶ partial ──收齐──▶ received
       └────────────────────────────── cancel ──────────────────────────┘
"""

from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, enum_type
from app.models.product import Sku
from app.models.supplier import Supplier
from app.models.user import User
from app.models.warehouse import Warehouse, WarehouseLocation


class PurchaseOrderStatus(str, Enum):
    DRAFT = "draft"            # 草稿
    SUBMITTED = "submitted"    # 已下单，待到货
    PARTIAL = "partial"        # 部分到货
    RECEIVED = "received"      # 已收齐
    CANCELLED = "cancelled"


class ReceiptStatus(str, Enum):
    POSTED = "posted"
    CANCELLED = "cancelled"


class PurchaseOrder(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("po_no", name="uq_purchase_orders_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    po_no: Mapped[str] = mapped_column(String(32), default="", nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    # 收货仓：货最终进哪个仓
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        enum_type(PurchaseOrderStatus, "purchase_order_status"),
        default=PurchaseOrderStatus.DRAFT,
        nullable=False,
    )
    ordered_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    expected_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    total_amount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    buyer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    supplier: Mapped[Supplier] = relationship(lazy="selectin")
    warehouse: Mapped[Warehouse] = relationship(lazy="selectin")
    buyer: Mapped[User | None] = relationship(lazy="selectin")
    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        back_populates="order", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def received_quantity(self) -> int:
        return sum(item.received_qty for item in self.items)

    @property
    def is_fully_received(self) -> bool:
        return all(item.received_qty >= item.quantity for item in self.items)

    @property
    def progress(self) -> str:
        return f"{self.received_quantity}/{self.total_quantity}"

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<PurchaseOrder {self.po_no} {self.status}>"


class PurchaseOrderItem(Base, TimestampMixin):
    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    received_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    defective_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    order: Mapped[PurchaseOrder] = relationship(back_populates="items")
    sku: Mapped[Sku] = relationship(lazy="selectin")

    @property
    def outstanding_qty(self) -> int:
        return max(0, self.quantity - self.received_qty)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<PurchaseOrderItem sku={self.sku_id} {self.received_qty}/{self.quantity}>"


class PurchaseReceipt(Base, TimestampMixin):
    """一次到货。一张采购单可以有多张，分批到货就这么记。"""

    __tablename__ = "purchase_receipts"
    __table_args__ = (UniqueConstraint("receipt_no", name="uq_purchase_receipts_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_no: Mapped[str] = mapped_column(String(32), default="", nullable=False, index=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[ReceiptStatus] = mapped_column(
        enum_type(ReceiptStatus, "receipt_status"),
        default=ReceiptStatus.POSTED,
        nullable=False,
    )
    received_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    received_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, default=None, nullable=True
    )
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    order: Mapped[PurchaseOrder] = relationship(lazy="selectin")
    warehouse: Mapped[Warehouse] = relationship(lazy="selectin")
    operator: Mapped[User | None] = relationship(lazy="selectin", foreign_keys=[received_by])
    items: Mapped[list["PurchaseReceiptItem"]] = relationship(
        back_populates="receipt", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def total_defective(self) -> int:
        return sum(item.defective_qty for item in self.items)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<PurchaseReceipt {self.receipt_no}>"


class PurchaseReceiptItem(Base, TimestampMixin):
    __tablename__ = "purchase_receipt_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_receipts.id", ondelete="CASCADE"), nullable=False
    )
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_items.id", ondelete="CASCADE"), nullable=False
    )
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False)
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouse_locations.id", ondelete="SET NULL"), default=None, nullable=True
    )
    # 本次到货总量；其中 defective_qty 是次品，其余是合格品。
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    defective_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    receipt: Mapped[PurchaseReceipt] = relationship(back_populates="items")
    order_item: Mapped[PurchaseOrderItem] = relationship(lazy="selectin")
    sku: Mapped[Sku] = relationship(lazy="selectin")
    location: Mapped[WarehouseLocation | None] = relationship(lazy="selectin")

    @property
    def qualified_qty(self) -> int:
        return self.quantity - self.defective_qty

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<PurchaseReceiptItem sku={self.sku_id} qty={self.quantity}>"
