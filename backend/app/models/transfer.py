"""多仓库调拨。

调拨的关键在于**在途**：货从调出仓发出去之后、调入仓收到之前，它既不在调出仓
的实际库存里，也不能算作调入仓的可售库存。少了对在途的显式建模，就会出现
「两边都看不到这批货」的黑洞。

本模块把在途记在**调入仓**（口径是「发往本仓的在途」），于是：

* 调出仓：实际库存 −N（可售随之减少）
* 调入仓：在途 +N（**不计入可售**）
* 收货后：调入仓在途 −N、实际库存 +N（次品单独进次品区）

状态机::

    pending ──approve──▶ approved ──ship──▶ in_transit ──receive──▶ received
       │                    │
       └── reject ──▶ rejected      └── cancel ──▶ cancelled
"""

from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, enum_type
from app.models.product import Sku
from app.models.user import User
from app.models.warehouse import Warehouse


class TransferStatus(str, Enum):
    PENDING = "pending"        # 待审批
    APPROVED = "approved"      # 已批准，待发出
    IN_TRANSIT = "in_transit"  # 已发出，在途
    RECEIVED = "received"      # 已收货
    REJECTED = "rejected"      # 审批驳回
    CANCELLED = "cancelled"    # 已取消


class StockTransfer(Base, TimestampMixin):
    __tablename__ = "stock_transfers"
    __table_args__ = (UniqueConstraint("transfer_no", name="uq_stock_transfers_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_no: Mapped[str] = mapped_column(String(32), default="", nullable=False, index=True)
    from_warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    to_warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[TransferStatus] = mapped_column(
        enum_type(TransferStatus, "transfer_status"),
        default=TransferStatus.PENDING,
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    requested_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    reject_reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    shipped_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    shipped_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    received_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    received_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)

    from_warehouse: Mapped[Warehouse] = relationship(
        lazy="selectin", foreign_keys=[from_warehouse_id]
    )
    to_warehouse: Mapped[Warehouse] = relationship(
        lazy="selectin", foreign_keys=[to_warehouse_id]
    )
    items: Mapped[list["StockTransferItem"]] = relationship(
        back_populates="transfer", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def shipped_quantity(self) -> int:
        return sum(item.shipped_qty for item in self.items)

    @property
    def received_quantity(self) -> int:
        return sum(item.received_qty for item in self.items)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<StockTransfer {self.transfer_no} {self.status}>"


class StockTransferItem(Base, TimestampMixin):
    __tablename__ = "stock_transfer_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[int] = mapped_column(
        ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)       # 申请调拨量
    shipped_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)   # 实际发出
    received_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 实收总量
    defective_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 其中次品
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    transfer: Mapped[StockTransfer] = relationship(back_populates="items")
    sku: Mapped[Sku] = relationship(lazy="selectin")

    @property
    def qualified_qty(self) -> int:
        return self.received_qty - self.defective_qty

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<StockTransferItem sku={self.sku_id} qty={self.quantity}>"
