"""退货单与质检分流（M7）。

退货的关键不是「收回来」，而是**收回来之后去哪里**。同一件退回来的衣服：

* 吊牌完好 → 可售，直接回到可售库存；
* 有污渍 → 次品，进次品区，永远不参与可售；
* 拉链坏了 → 维修，进维修区，修好之后再决定；
* 破得没法修 → 报损，走 damage_scrap 流水。

四个结论走四条不同的库存流水，混成一个「退货入库」会让后面的库存报表彻底
失真 —— 这也是这个模块存在的唯一理由。
"""

from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, enum_type
from app.models.channel import Channel
from app.models.order import SalesOrder
from app.models.product import Sku
from app.models.user import User
from app.models.warehouse import Warehouse


class ReturnStatus(str, Enum):
    PENDING = "pending"      # 已受理，待质检
    INSPECTED = "inspected"  # 已质检分流，待入库
    INBOUND = "inbound"      # 已入库，库存已落账
    CANCELLED = "cancelled"


class ReturnReason(str, Enum):
    QUALITY = "quality"                 # 质量问题
    WRONG_ITEM = "wrong_item"           # 发错货
    DAMAGED = "damaged"                 # 运输破损
    NO_LONGER_WANTED = "no_longer_wanted"  # 七天无理由
    OTHER = "other"


class ReturnDisposition(str, Enum):
    """质检结论。决定了这一行走哪条库存流水。"""

    RESELLABLE = "resellable"  # 可售 → 回可售库存
    DEFECTIVE = "defective"    # 次品 → 次品区
    REPAIR = "repair"          # 维修 → 维修区
    SCRAP = "scrap"            # 报损 → 报损流水


class ReturnOrder(Base, TimestampMixin):
    """一张退货单。可以关联到系统内的原订单，也允许只带一个渠道单号。"""

    __tablename__ = "return_orders"
    __table_args__ = (UniqueConstraint("return_no", name="uq_return_orders_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    return_no: Mapped[str] = mapped_column(String(32), default="", nullable=False, index=True)

    # 原订单：有则能做「已售 - 已退」校验，没有就只按渠道单号记录。
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="SET NULL"), default=None, nullable=True
    )
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), default=None, nullable=True
    )
    channel_order_no: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    buyer_nick: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )

    status: Mapped[ReturnStatus] = mapped_column(
        enum_type(ReturnStatus, "return_status"), default=ReturnStatus.PENDING, nullable=False
    )
    reason: Mapped[ReturnReason] = mapped_column(
        enum_type(ReturnReason, "return_reason"), default=ReturnReason.OTHER, nullable=False
    )

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    inspected_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    inspected_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    inbound_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    inbound_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)

    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    order: Mapped[SalesOrder | None] = relationship(lazy="selectin")
    channel: Mapped[Channel | None] = relationship(lazy="selectin")
    warehouse: Mapped[Warehouse] = relationship(lazy="selectin")
    items: Mapped[list["ReturnOrderItem"]] = relationship(
        back_populates="return_order", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def is_inspected(self) -> bool:
        return all(item.disposition is not None for item in self.items)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<ReturnOrder {self.return_no} {self.status}>"


class ReturnOrderItem(Base, TimestampMixin):
    """一行退货 + 它的质检分流结果。

    ``sold_qty`` 是**下这张退货单时**原订单该 SKU 的销量快照。把销量落在行上，
    而不是每次实时反查，是因为订单可能被改、也可能查不到 —— 校验必须有一份
    自己可信的基准。
    """

    __tablename__ = "return_order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    return_id: Mapped[int] = mapped_column(
        ForeignKey("return_orders.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False)

    # 申请退货量 + 当时可用于校验的销量基准
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    sold_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    disposition: Mapped[ReturnDisposition | None] = mapped_column(
        enum_type(ReturnDisposition, "return_disposition"), default=None, nullable=True
    )
    # 质检分流：四者之和等于 quantity（报损也算"已处理"）。
    resellable_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    defective_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    repair_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scrap_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    return_order: Mapped[ReturnOrder] = relationship(back_populates="items")
    sku: Mapped[Sku] = relationship(lazy="selectin")

    @property
    def inspected_total(self) -> int:
        return self.resellable_qty + self.defective_qty + self.repair_qty + self.scrap_qty

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<ReturnOrderItem sku={self.sku_id} qty={self.quantity} disp={self.disposition}>"
