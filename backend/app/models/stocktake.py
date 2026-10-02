"""盘点任务与差异调整（M7）。

盘点的价值全在**差异**上，所以差异不能自己悄悄改库存：

    draft ──提交──▶ submitted ──审核──▶ approved（这时才写调整流水）
      └── 差异超过阈值且未审核 ──▶ 40304，必须有人过目

``book_qty`` 是建单那一刻的账面快照。如果实盘期间又发生了出入库，差异会显得
不合理 —— 但这是盘点本身的固有问题，把账面冻结在快照上至少让「差异」
这个数字可复现。
"""

from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, enum_type
from app.models.product import Sku
from app.models.user import User
from app.models.warehouse import Warehouse


class StocktakeStatus(str, Enum):
    DRAFT = "draft"          # 盘点中，可反复录入
    SUBMITTED = "submitted"  # 已提交，待审核
    APPROVED = "approved"    # 已审核，差异已落账
    CANCELLED = "cancelled"


class Stocktake(Base, TimestampMixin):
    __tablename__ = "stocktakes"
    __table_args__ = (UniqueConstraint("stocktake_no", name="uq_stocktakes_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stocktake_no: Mapped[str] = mapped_column(String(32), default="", nullable=False, index=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[StocktakeStatus] = mapped_column(
        enum_type(StocktakeStatus, "stocktake_status"),
        default=StocktakeStatus.DRAFT,
        nullable=False,
    )
    # 盘点范围说明，例如「A 区」「全部」；不参与计算，只给人看。
    scope: Mapped[str] = mapped_column(String(120), default="", nullable=False)

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    submitted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    warehouse: Mapped[Warehouse] = relationship(lazy="selectin")
    items: Mapped[list["StocktakeItem"]] = relationship(
        back_populates="stocktake", lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def counted_lines(self) -> int:
        return sum(1 for item in self.items if item.counted_qty is not None)

    @property
    def variance_lines(self) -> int:
        return sum(1 for item in self.items if item.counted_qty is not None and item.variance_qty != 0)

    @property
    def total_variance(self) -> int:
        return sum(item.variance_qty for item in self.items)

    @property
    def max_abs_variance(self) -> int:
        return max((abs(item.variance_qty) for item in self.items if item.counted_qty is not None), default=0)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Stocktake {self.stocktake_no} {self.status}>"


class StocktakeItem(Base, TimestampMixin):
    __tablename__ = "stocktake_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    stocktake_id: Mapped[int] = mapped_column(
        ForeignKey("stocktakes.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False)

    # 建单时的账面快照
    book_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 实盘数；None 表示这一行还没盘
    counted_qty: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True)
    counted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    counted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # 差异是否已经落账
    adjusted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    stocktake: Mapped[Stocktake] = relationship(back_populates="items")
    sku: Mapped[Sku] = relationship(lazy="selectin")

    @property
    def variance_qty(self) -> int:
        """差异 = 实盘 - 账面。未盘的行算作 0 差异。"""
        if self.counted_qty is None:
            return 0
        return self.counted_qty - self.book_qty

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<StocktakeItem sku={self.sku_id} book={self.book_qty} counted={self.counted_qty}>"
