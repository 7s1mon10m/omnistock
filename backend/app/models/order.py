"""Synced e-commerce orders and the bookkeeping around them.

The order status machine (see the project document) is:

    pending_payment → pending_fulfillment → reserved → picking → shipped → completed
                            ↓                     ↓
                        exception            cancelled

M2 implements everything up to ``reserved``; ``picking``/``shipped`` arrive in
M3.  Stock is never moved directly here — ordering goes through
:mod:`app.services.order_service`, which writes ledger rows like everything else.
"""

from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, enum_type
from app.models.channel import Channel, ChannelShop
from app.models.product import Sku
from app.models.user import User
from app.models.warehouse import Warehouse


class OrderStatus(str, Enum):
    PENDING_PAYMENT = "pending_payment"
    PENDING_FULFILLMENT = "pending_fulfillment"
    RESERVED = "reserved"
    PICKING = "picking"
    SHIPPED = "shipped"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXCEPTION = "exception"


class OrderSource(str, Enum):
    IMPORT_CSV = "import_csv"
    IMPORT_JSON = "import_json"
    ADAPTER = "adapter"
    MANUAL = "manual"


class SyncResult(str, Enum):
    CREATED = "created"
    DUPLICATE = "duplicate"
    FAILED = "failed"


class ExceptionType(str, Enum):
    STOCK_SHORTAGE = "stock_shortage"
    MAPPING_MISSING = "mapping_missing"
    OTHER = "other"


class ExceptionStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class SalesOrder(Base, TimestampMixin, SoftDeleteMixin):
    """One order as it arrived from a channel."""

    __tablename__ = "sales_orders"
    __table_args__ = (
        # The database level guard against a duplicated sync booking stock twice.
        UniqueConstraint("channel_id", "channel_order_no", name="uq_orders_channel_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(32), default="", nullable=False, index=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="RESTRICT"), nullable=False
    )
    shop_id: Mapped[int | None] = mapped_column(
        ForeignKey("channel_shops.id", ondelete="SET NULL"), default=None, nullable=True
    )
    channel_order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        enum_type(OrderStatus, "order_status"),
        default=OrderStatus.PENDING_PAYMENT,
        nullable=False,
    )
    # The warehouse the order is fulfilled from; defaults to the main one.
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouses.id", ondelete="SET NULL"), default=None, nullable=True
    )
    buyer_nick: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    total_amount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_bundle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    source: Mapped[OrderSource] = mapped_column(
        enum_type(OrderSource, "order_source"), default=OrderSource.MANUAL, nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), default=None, nullable=True, unique=True
    )
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    channel: Mapped[Channel] = relationship(lazy="selectin")
    shop: Mapped[ChannelShop | None] = relationship(lazy="selectin")
    warehouse: Mapped[Warehouse | None] = relationship(lazy="selectin")
    items: Mapped[list["SalesOrderItem"]] = relationship(
        back_populates="order", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<SalesOrder {self.order_no or self.channel_order_no} {self.status}>"


class SalesOrderItem(Base, TimestampMixin):
    """One line of an order, always resolved to an internal SKU.

    ``sku_id`` may point at a bundle SKU; the explosion into component SKUs
    happens at reservation time and is recorded in the inventory ledger.
    """

    __tablename__ = "sales_order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    channel_product_code: Mapped[str] = mapped_column(String(64), nullable=False)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_bundle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    order: Mapped[SalesOrder] = relationship(back_populates="items")
    sku: Mapped[Sku] = relationship(lazy="selectin")


class ImportBatch(Base, TimestampMixin):
    """One uploaded CSV/JSON file and its outcome."""

    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), default=None, nullable=True
    )
    source: Mapped[OrderSource] = mapped_column(
        enum_type(OrderSource, "order_source"), default=OrderSource.IMPORT_CSV, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exception_orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # [{row: 3, code: 40020, message: "..."}]
    errors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    operator_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )

    operator: Mapped[User | None] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<ImportBatch {self.id} ok={self.created_orders} dup={self.duplicate_orders}>"


class OrderSyncLog(Base, TimestampMixin):
    """One row per order seen by a sync run.

    This is what makes "重复同步" observable: a re-synced order shows up as a
    ``duplicate`` line instead of silently booking stock a second time.
    """

    __tablename__ = "order_sync_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int | None] = mapped_column(
        ForeignKey("channel_shops.id", ondelete="SET NULL"), default=None, nullable=True
    )
    channel_order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="SET NULL"), default=None, nullable=True
    )
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), default=None, nullable=True
    )
    result: Mapped[SyncResult] = mapped_column(
        enum_type(SyncResult, "sync_result"), default=SyncResult.CREATED, nullable=False
    )
    message: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    channel: Mapped[Channel] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<OrderSyncLog {self.channel_order_no} {self.result}>"


class OrderException(Base, TimestampMixin):
    """A problem that stopped an order from being fulfilled."""

    __tablename__ = "order_exceptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False
    )
    sku_id: Mapped[int | None] = mapped_column(
        ForeignKey("skus.id", ondelete="SET NULL"), default=None, nullable=True
    )
    type: Mapped[ExceptionType] = mapped_column(
        enum_type(ExceptionType, "exception_type"),
        default=ExceptionType.STOCK_SHORTAGE,
        nullable=False,
    )
    status: Mapped[ExceptionStatus] = mapped_column(
        enum_type(ExceptionStatus, "exception_status"),
        default=ExceptionStatus.OPEN,
        nullable=False,
    )
    required_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )

    order: Mapped[SalesOrder] = relationship(lazy="selectin")
    sku: Mapped[Sku | None] = relationship(lazy="selectin")

    @property
    def shortage_qty(self) -> int:
        return max(0, self.required_qty - self.available_qty)
