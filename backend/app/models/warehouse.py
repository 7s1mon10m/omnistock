"""Warehouses and their storage locations.

A small e-commerce team typically runs a head office warehouse, a live-stream
warehouse and a return warehouse, so the type is modelled explicitly.
"""

from __future__ import annotations

from enum import Enum

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, enum_type


class WarehouseType(str, Enum):
    MAIN = "main"        # 总仓
    LIVE = "live"        # 直播间仓
    RETURN = "return"    # 退货仓
    OTHER = "other"


class Warehouse(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "warehouses"
    __table_args__ = (UniqueConstraint("code", name="uq_warehouses_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[WarehouseType] = mapped_column(
        enum_type(WarehouseType, "warehouse_type"), default=WarehouseType.MAIN, nullable=False
    )
    address: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    contact_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    locations: Mapped[list["WarehouseLocation"]] = relationship(
        back_populates="warehouse", lazy="selectin", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Warehouse {self.code}>"


class WarehouseLocation(Base, TimestampMixin):
    """A bin / shelf inside a warehouse; picking is sorted by ``code``."""

    __tablename__ = "warehouse_locations"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "code", name="uq_locations_warehouse_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # e.g. "A 区 / 常温区"; kept free-form for now.
    zone: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    warehouse: Mapped[Warehouse] = relationship(back_populates="locations")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<WarehouseLocation {self.code}@{self.warehouse_id}>"
