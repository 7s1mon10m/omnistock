"""Suppliers — the counterparty of every purchase order."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin


class Supplier(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("code", name="uq_suppliers_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    address: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # 结算方式，例如「月结 30 天」
    payment_terms: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # 交期（天）：新建采购单时用来推算预计到货日
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Supplier {self.code}>"
