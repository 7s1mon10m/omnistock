"""Shipping: pick lists, scan records, packing and outbound.

A shipment is the bridge between "we hold stock for this order" and "the parcel
left the building".  The pick list is derived from the inventory ledger — the
same rows M2 wrote when it reserved stock — so what gets picked is exactly what
is held, and shipping turns those reservations into a real outbound movement.

状态机::

    pending ──claim──▶ picking ──all picked──▶ picked ──pack──▶ packed ──ship──▶ shipped
        └──────────────────── cancel ────────────────────┘
"""

from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, enum_type
from app.models.order import SalesOrder, SalesOrderItem
from app.models.product import Sku
from app.models.user import User
from app.models.warehouse import Warehouse, WarehouseLocation


class ShipmentStatus(str, Enum):
    PENDING = "pending"      # 待拣货
    PICKING = "picking"      # 拣货中
    PICKED = "picked"        # 拣货完成
    PACKED = "packed"        # 已复核打包
    SHIPPED = "shipped"      # 已出库发货
    CANCELLED = "cancelled"  # 已取消


class ShipmentItemStatus(str, Enum):
    PENDING = "pending"
    PICKED = "picked"


class PickResult(str, Enum):
    OK = "ok"
    WRONG_SKU = "wrong_sku"
    BARCODE_NOT_FOUND = "barcode_not_found"
    OVER_QUANTITY = "over_quantity"
    NOT_ON_LIST = "not_on_list"


class Shipment(Base, TimestampMixin):
    """One pick-and-pack job for one sales order."""

    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("shipment_no", name="uq_shipments_no"),
        # At most one *live* shipment per order.  A partial unique index is what
        # actually stops two warehouse tablets from opening the same pick list
        # simultaneously — a service-level check alone would race.
        Index(
            "uq_shipments_active_order",
            "order_id",
            unique=True,
            sqlite_where=text("status != 'cancelled'"),
            postgresql_where=text("status != 'cancelled'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_no: Mapped[str] = mapped_column(String(32), default="", nullable=False, index=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[ShipmentStatus] = mapped_column(
        enum_type(ShipmentStatus, "shipment_status"),
        default=ShipmentStatus.PENDING,
        nullable=False,
    )

    picker_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    picked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)

    packed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    packed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    package_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    weight_g: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    carrier: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    tracking_no: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    shipped_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    shipped_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)

    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    order: Mapped[SalesOrder] = relationship(lazy="selectin")
    warehouse: Mapped[Warehouse] = relationship(lazy="selectin")
    picker: Mapped[User | None] = relationship(lazy="selectin", foreign_keys=[picker_id])
    items: Mapped[list["ShipmentItem"]] = relationship(
        back_populates="shipment", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def picked_quantity(self) -> int:
        return sum(item.picked_qty for item in self.items)

    @property
    def is_fully_picked(self) -> bool:
        return all(item.picked_qty >= item.quantity for item in self.items)

    @property
    def progress(self) -> str:
        return f"{self.picked_quantity}/{self.total_quantity}"

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Shipment {self.shipment_no} {self.status}>"


class ShipmentItem(Base, TimestampMixin):
    """One physical SKU to pick, already exploded out of any bundle.

    ``label`` is the human name of the standing location; sorting the pick list
    by ``(warehouse, location_code)`` is what gives the picker a walking route.
    """

    __tablename__ = "shipment_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    # The order line this came from; a bundle line produces several pick rows.
    order_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_order_items.id", ondelete="SET NULL"), default=None, nullable=True
    )
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False)
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouse_locations.id", ondelete="SET NULL"), default=None, nullable=True
    )

    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    picked_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[ShipmentItemStatus] = mapped_column(
        enum_type(ShipmentItemStatus, "shipment_item_status"),
        default=ShipmentItemStatus.PENDING,
        nullable=False,
    )
    picked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    picked_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    # Picking sequence within the shipment, assigned when the pick list is built.
    line_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    shipment: Mapped[Shipment] = relationship(back_populates="items")
    order_item: Mapped[SalesOrderItem | None] = relationship(lazy="selectin")
    sku: Mapped[Sku] = relationship(lazy="selectin")
    location: Mapped[WarehouseLocation | None] = relationship(lazy="selectin")

    @property
    def is_done(self) -> bool:
        return self.picked_qty >= self.quantity

    @property
    def location_code(self) -> str:
        return self.location.code if self.location else ""

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<ShipmentItem {self.sku_id} {self.picked_qty}/{self.quantity}>"


class PickRecord(Base, TimestampMixin):
    """Every scan, including the rejected ones.

    Kept even when the scan is refused — a run of ``wrong_sku`` rows is exactly
    the signal that something is misplaced in the warehouse.
    """

    __tablename__ = "pick_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    shipment_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipment_items.id", ondelete="SET NULL"), default=None, nullable=True
    )
    sku_id: Mapped[int | None] = mapped_column(
        ForeignKey("skus.id", ondelete="SET NULL"), default=None, nullable=True
    )
    barcode: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result: Mapped[PickResult] = mapped_column(
        enum_type(PickResult, "pick_result"), default=PickResult.OK, nullable=False
    )
    accepted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    message: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    operator_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )

    sku: Mapped[Sku | None] = relationship(lazy="selectin")
    operator: Mapped[User | None] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<PickRecord {self.barcode} {self.result}>"
