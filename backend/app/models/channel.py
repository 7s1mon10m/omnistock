"""Sales channels, their shops, and the channel-product mapping.

A channel is the platform (淘宝 / 抖音 / Shopify); a shop is one storefront on
that platform.  ``channel_products`` is the bridge that makes multi-channel
selling possible: every external product code is resolved to one internal SKU
before it can ever touch stock.
"""

from __future__ import annotations

from enum import Enum

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, enum_type
from app.models.product import Sku


class ChannelPlatform(str, Enum):
    TAOBAO = "taobao"
    DOUYIN = "douyin"
    SHOPIFY = "shopify"
    JD = "jd"
    PDD = "pdd"
    OTHER = "other"


class Channel(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "channels"
    __table_args__ = (UniqueConstraint("code", name="uq_channels_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    platform: Mapped[ChannelPlatform] = mapped_column(
        enum_type(ChannelPlatform, "channel_platform"),
        default=ChannelPlatform.OTHER,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    shops: Mapped[list["ChannelShop"]] = relationship(
        back_populates="channel", lazy="selectin", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Channel {self.code}>"


class ChannelShop(Base, TimestampMixin):
    """One storefront on a channel, e.g. the flagship Taobao store."""

    __tablename__ = "channel_shops"
    __table_args__ = (UniqueConstraint("channel_id", "code", name="uq_shops_channel_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    channel: Mapped[Channel] = relationship(back_populates="shops")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<ChannelShop {self.code}@{self.channel_id}>"


class ChannelProduct(Base, TimestampMixin):
    """Maps an external product code onto one internal SKU.

    ``TB-100238`` (Taobao), ``DY-883021`` (Douyin) and ``SHOP-TS-001`` (Shopify)
    can all point at the same internal ``TSHIRT-WHITE-L``, which is what makes
    one stock pool serve every platform.
    """

    __tablename__ = "channel_products"
    __table_args__ = (
        UniqueConstraint("channel_id", "channel_product_code", name="uq_channel_product_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    # Optional: the same external code may be scoped to a specific shop.
    shop_id: Mapped[int | None] = mapped_column(
        ForeignKey("channel_shops.id", ondelete="SET NULL"), default=None, nullable=True
    )
    channel_product_code: Mapped[str] = mapped_column(String(64), nullable=False)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="CASCADE"), nullable=False)
    channel_title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    channel: Mapped[Channel] = relationship(lazy="selectin")
    shop: Mapped[ChannelShop | None] = relationship(lazy="selectin")
    sku: Mapped[Sku] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<ChannelProduct {self.channel_product_code}->{self.sku_id}>"
