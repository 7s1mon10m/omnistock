"""Data access for channels, shops and channel-product mappings."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.channel import Channel, ChannelProduct, ChannelShop
from app.utils.pagination import PageResult, paginate

# -------------------------------------------------------------------- channel


def get_channel(session: Session, channel_id: int) -> Channel | None:
    channel = session.get(Channel, channel_id)
    if channel is None or channel.deleted_at is not None:
        return None
    return channel


def get_channel_by_code(session: Session, code: str) -> Channel | None:
    stmt = select(Channel).where(Channel.code == code, Channel.deleted_at.is_(None))
    return session.scalar(stmt)


def list_channels(
    session: Session,
    *,
    keyword: str | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(Channel).where(Channel.deleted_at.is_(None))
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(or_(Channel.code.like(pattern), Channel.name.like(pattern)))
    if is_active is not None:
        stmt = stmt.where(Channel.is_active.is_(is_active))
    stmt = stmt.order_by(Channel.id)
    return paginate(session, stmt, page, page_size)


def create_channel(session: Session, **fields) -> Channel:
    channel = Channel(**fields)
    session.add(channel)
    session.flush()
    return channel


def count_shops(session: Session, channel_id: int) -> int:
    stmt = select(func.count()).select_from(ChannelShop).where(ChannelShop.channel_id == channel_id)
    return session.scalar(stmt) or 0


def count_channel_products(session: Session, channel_id: int) -> int:
    stmt = select(func.count()).select_from(ChannelProduct).where(
        ChannelProduct.channel_id == channel_id
    )
    return session.scalar(stmt) or 0


# ----------------------------------------------------------------------- shop


def get_shop(session: Session, shop_id: int) -> ChannelShop | None:
    return session.get(ChannelShop, shop_id)


def get_shop_by_code(session: Session, channel_id: int, code: str) -> ChannelShop | None:
    stmt = select(ChannelShop).where(
        ChannelShop.channel_id == channel_id, ChannelShop.code == code
    )
    return session.scalar(stmt)


def list_shops(session: Session, channel_id: int) -> list[ChannelShop]:
    stmt = (
        select(ChannelShop)
        .where(ChannelShop.channel_id == channel_id)
        .order_by(ChannelShop.code)
    )
    return list(session.scalars(stmt).all())


def create_shop(session: Session, **fields) -> ChannelShop:
    shop = ChannelShop(**fields)
    session.add(shop)
    session.flush()
    return shop


# ----------------------------------------------------------- product mapping


def get_channel_product(session: Session, mapping_id: int) -> ChannelProduct | None:
    return session.get(ChannelProduct, mapping_id)


def get_mapping(session: Session, channel_id: int, code: str) -> ChannelProduct | None:
    """Resolve an external product code to its internal SKU.

    Prefers an active mapping; a disabled one is still returned so callers can
    raise a precise error instead of a generic "not found".
    """
    stmt = (
        select(ChannelProduct)
        .where(
            ChannelProduct.channel_id == channel_id,
            ChannelProduct.channel_product_code == code,
        )
        .order_by(ChannelProduct.is_active.desc(), ChannelProduct.id)
    )
    return session.scalar(stmt)


def list_channel_products(
    session: Session,
    *,
    channel_id: int | None = None,
    sku_id: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(ChannelProduct).options(
        selectinload(ChannelProduct.channel),
        selectinload(ChannelProduct.shop),
        selectinload(ChannelProduct.sku),
    )
    if channel_id:
        stmt = stmt.where(ChannelProduct.channel_id == channel_id)
    if sku_id:
        stmt = stmt.where(ChannelProduct.sku_id == sku_id)
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                ChannelProduct.channel_product_code.like(pattern),
                ChannelProduct.channel_title.like(pattern),
            )
        )
    stmt = stmt.order_by(ChannelProduct.id.desc())
    return paginate(session, stmt, page, page_size)


def create_channel_product(session: Session, **fields) -> ChannelProduct:
    mapping = ChannelProduct(**fields)
    session.add(mapping)
    session.flush()
    return mapping
