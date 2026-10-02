"""The three product layers: SPU, SKU and bundle (组合商品).

* **SPU** — what is being sold, e.g. "纯棉短袖".
* **SKU** — the unit that actually holds stock and price, e.g. "白色 / L 码".
* **Bundle** — a set made of several SKUs, e.g. "洗发水 + 护发素套装".

A bundle never holds stock itself: at order time it is exploded into its
component SKUs and the components are what get reserved.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from sqlalchemy import (
    Boolean,
        ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, enum_type


class SpuType(str, Enum):
    SINGLE = "single"    # 普通商品
    BUNDLE = "bundle"    # 组合商品


class SpuStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class SkuStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Spu(Base, TimestampMixin, SoftDeleteMixin):
    """Standard product unit — the marketing level description."""

    __tablename__ = "spus"
    __table_args__ = (UniqueConstraint("code", name="uq_spus_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    brand: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    type: Mapped[SpuType] = mapped_column(
        enum_type(SpuType, "spu_type"), default=SpuType.SINGLE, nullable=False
    )
    # List of image URLs; JSON keeps SQLite and PostgreSQL identical.
    images: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    description: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    status: Mapped[SpuStatus] = mapped_column(
        enum_type(SpuStatus, "spu_status"), default=SpuStatus.ACTIVE, nullable=False
    )

    skus: Mapped[list["Sku"]] = relationship(
        back_populates="spu", lazy="selectin", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Spu {self.code}>"


class Sku(Base, TimestampMixin, SoftDeleteMixin):
    """Stock keeping unit — the level that carries stock, price and barcode."""

    __tablename__ = "skus"
    __table_args__ = (
        UniqueConstraint("sku_code", name="uq_skus_sku_code"),
        UniqueConstraint("barcode", name="uq_skus_barcode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    spu_id: Mapped[int] = mapped_column(ForeignKey("spus.id", ondelete="CASCADE"), nullable=False)
    sku_code: Mapped[str] = mapped_column(String(64), nullable=False)
    # e.g. {"color": "白", "size": "L"}
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(64), default=None, nullable=True)
    weight_g: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    package_spec: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    purchase_price_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Default supplier; the suppliers table arrives in M4 so this stays a plain
    # integer reference for now.
    default_supplier_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True)
    # Safety stock copied into every new inventory row for this SKU.
    safety_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[SkuStatus] = mapped_column(
        enum_type(SkuStatus, "sku_status"), default=SkuStatus.ACTIVE, nullable=False
    )

    spu: Mapped[Spu] = relationship(back_populates="skus")
    barcodes: Mapped[list["SkuBarcode"]] = relationship(
        back_populates="sku", lazy="selectin", cascade="all, delete-orphan"
    )
    components: Mapped[list["BundleComponent"]] = relationship(
        foreign_keys="BundleComponent.bundle_sku_id",
        back_populates="bundle_sku",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    @property
    def display_name(self) -> str:
        spec = " / ".join(str(v) for v in self.spec_json.values())
        return f"{self.spu.name} {spec}".strip() if self.spu else self.sku_code

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Sku {self.sku_code}>"


class SkuBarcode(Base, TimestampMixin):
    """Extra barcodes / QR codes a SKU answers to (the primary lives on Sku)."""

    __tablename__ = "sku_barcodes"
    __table_args__ = (UniqueConstraint("barcode", name="uq_sku_barcodes_barcode"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="CASCADE"), nullable=False)
    barcode: Mapped[str] = mapped_column(String(64), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    remark: Mapped[str] = mapped_column(String(128), default="", nullable=False)

    sku: Mapped[Sku] = relationship(back_populates="barcodes")


class BundleComponent(Base, TimestampMixin):
    """One line of a bundle: which component SKU, and how many of it."""

    __tablename__ = "bundle_components"
    __table_args__ = (
        UniqueConstraint("bundle_sku_id", "component_sku_id", name="uq_bundle_component"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bundle_sku_id: Mapped[int] = mapped_column(
        ForeignKey("skus.id", ondelete="CASCADE"), nullable=False
    )
    component_sku_id: Mapped[int] = mapped_column(
        ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    bundle_sku: Mapped[Sku] = relationship(
        foreign_keys=[bundle_sku_id], back_populates="components"
    )
    component_sku: Mapped[Sku] = relationship(foreign_keys=[component_sku_id], lazy="selectin")
