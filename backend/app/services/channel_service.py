"""Channel, shop and channel-product mapping services."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import (
    CHANNEL_CODE_DUPLICATE,
    CHANNEL_MAPPING_NOT_FOUND,
    CHANNEL_NOT_FOUND,
    CHANNEL_PRODUCT_DUPLICATE,
    CHANNEL_SHOP_CODE_DUPLICATE,
    CHANNEL_SHOP_NOT_FOUND,
    SKU_NOT_FOUND,
    BusinessError,
)
from app.models.channel import Channel, ChannelProduct, ChannelShop
from app.repositories import channel_repo, product_repo
from app.schemas.channel import (
    ChannelCreate,
    ChannelProductCreate,
    ChannelProductRead,
    ChannelProductUpdate,
    ChannelRead,
    ChannelUpdate,
    ShopCreate,
    ShopRead,
)


# --------------------------------------------------------------------- channel
def get_channel_or_404(session: Session, channel_id: int) -> Channel:
    channel = channel_repo.get_channel(session, channel_id)
    if channel is None:
        raise BusinessError(CHANNEL_NOT_FOUND, http_status=404)
    return channel


def get_channel_by_code_or_404(session: Session, code: str) -> Channel:
    channel = channel_repo.get_channel_by_code(session, code)
    if channel is None:
        raise BusinessError(
            CHANNEL_NOT_FOUND, detail={"code": code}, http_status=404
        )
    return channel


def create_channel(session: Session, payload: ChannelCreate) -> Channel:
    if channel_repo.get_channel_by_code(session, payload.code) is not None:
        raise BusinessError(CHANNEL_CODE_DUPLICATE, detail={"code": payload.code}, http_status=409)
    channel = channel_repo.create_channel(session, **payload.model_dump())
    session.commit()
    return channel


def update_channel(session: Session, channel: Channel, payload: ChannelUpdate) -> Channel:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(channel, field, value)
    session.commit()
    return channel


def to_channel_read(session: Session, channel: Channel) -> ChannelRead:
    return ChannelRead(
        id=channel.id,
        code=channel.code,
        name=channel.name,
        platform=channel.platform,
        is_active=channel.is_active,
        remark=channel.remark,
        shop_count=channel_repo.count_shops(session, channel.id),
        product_count=channel_repo.count_channel_products(session, channel.id),
        created_at=channel.created_at,
    )


def list_channel_reads(session: Session, page_result) -> list[ChannelRead]:
    return [to_channel_read(session, channel) for channel in page_result.items]


# ------------------------------------------------------------------------ shop
def create_shop(session: Session, channel_id: int, payload: ShopCreate) -> ChannelShop:
    get_channel_or_404(session, channel_id)
    if channel_repo.get_shop_by_code(session, channel_id, payload.code) is not None:
        raise BusinessError(
            CHANNEL_SHOP_CODE_DUPLICATE,
            detail={"channel_id": channel_id, "code": payload.code},
            http_status=409,
        )
    shop = channel_repo.create_shop(
        session, channel_id=channel_id, code=payload.code, name=payload.name, remark=payload.remark
    )
    session.commit()
    return shop


def list_shops(session: Session, channel_id: int) -> list[ChannelShop]:
    get_channel_or_404(session, channel_id)
    return channel_repo.list_shops(session, channel_id)


def to_shop_read(shop: ChannelShop) -> ShopRead:
    return ShopRead(
        id=shop.id,
        channel_id=shop.channel_id,
        code=shop.code,
        name=shop.name,
        is_active=shop.is_active,
        remark=shop.remark,
    )


# --------------------------------------------------------- product mapping
def create_mapping(session: Session, payload: ChannelProductCreate) -> ChannelProduct:
    get_channel_or_404(session, payload.channel_id)
    if payload.shop_id is not None:
        shop = channel_repo.get_shop(session, payload.shop_id)
        if shop is None or shop.channel_id != payload.channel_id:
            raise BusinessError(
                CHANNEL_SHOP_NOT_FOUND, detail={"shop_id": payload.shop_id}, http_status=404
            )
    if product_repo.get_sku(session, payload.sku_id) is None:
        raise BusinessError(SKU_NOT_FOUND, detail={"sku_id": payload.sku_id}, http_status=404)

    existing = channel_repo.get_mapping(
        session, payload.channel_id, payload.channel_product_code
    )
    if existing is not None:
        raise BusinessError(
            CHANNEL_PRODUCT_DUPLICATE,
            detail={
                "channel_id": payload.channel_id,
                "channel_product_code": payload.channel_product_code,
                "mapped_sku_id": existing.sku_id,
            },
            http_status=409,
        )

    mapping = channel_repo.create_channel_product(session, **payload.model_dump())
    session.commit()
    return mapping


def update_mapping(
    session: Session, mapping: ChannelProduct, payload: ChannelProductUpdate
) -> ChannelProduct:
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("sku_id") is not None and product_repo.get_sku(session, changes["sku_id"]) is None:
        raise BusinessError(SKU_NOT_FOUND, detail={"sku_id": changes["sku_id"]}, http_status=404)
    if changes.get("shop_id") is not None:
        shop = channel_repo.get_shop(session, changes["shop_id"])
        if shop is None or shop.channel_id != mapping.channel_id:
            raise BusinessError(
                CHANNEL_SHOP_NOT_FOUND, detail={"shop_id": changes["shop_id"]}, http_status=404
            )
    for field, value in changes.items():
        setattr(mapping, field, value)
    session.commit()
    return mapping


def delete_mapping(session: Session, mapping: ChannelProduct) -> None:
    session.delete(mapping)
    session.commit()


def to_mapping_read(mapping: ChannelProduct) -> ChannelProductRead:
    return ChannelProductRead(
        id=mapping.id,
        channel_id=mapping.channel_id,
        channel_code=mapping.channel.code if mapping.channel else "",
        channel_name=mapping.channel.name if mapping.channel else "",
        shop_id=mapping.shop_id,
        shop_code=mapping.shop.code if mapping.shop else "",
        channel_product_code=mapping.channel_product_code,
        sku_id=mapping.sku_id,
        sku_code=mapping.sku.sku_code if mapping.sku else "",
        sku_name=mapping.sku.display_name if mapping.sku else "",
        channel_title=mapping.channel_title,
        is_active=mapping.is_active,
        remark=mapping.remark,
        created_at=mapping.created_at,
    )


def resolve_sku_id(session: Session, channel_id: int, code: str) -> int:
    """External product code → internal SKU id, or a precise business error."""
    mapping = channel_repo.get_mapping(session, channel_id, code)
    if mapping is None:
        raise BusinessError(
            CHANNEL_MAPPING_NOT_FOUND,
            f"渠道商品 {code} 尚未映射到内部 SKU",
            detail={"channel_id": channel_id, "channel_product_code": code},
            http_status=400,
        )
    if not mapping.is_active:
        raise BusinessError(
            CHANNEL_MAPPING_NOT_FOUND,
            f"渠道商品 {code} 的映射已停用",
            detail={"channel_id": channel_id, "channel_product_code": code},
            http_status=400,
        )
    return mapping.sku_id
