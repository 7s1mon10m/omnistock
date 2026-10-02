"""Channel, shop and channel-product mapping endpoints.

``channel_products`` is the heart of multi-channel selling: it is what lets
``TB-100238``, ``DY-883021`` and ``SHOP-TS-001`` all draw on the same internal
SKU and therefore the same stock pool.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.v1.guards import OperatorGuard, ViewerGuard
from app.core.deps import DbSession
from app.core.errors import CHANNEL_PRODUCT_NOT_FOUND, BusinessError
from app.repositories import channel_repo
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
from app.schemas.common import Page
from app.services import channel_service

router = APIRouter(tags=["channels"])


# -------------------------------------------------------------------- channel
@router.get("/channels", response_model=Page[ChannelRead], summary="渠道列表")
def list_channels(
    session: DbSession,
    _: ViewerGuard,
    keyword: str | None = None,
    is_active: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[ChannelRead]:
    result = channel_repo.list_channels(
        session, keyword=keyword, is_active=is_active, page=page, page_size=page_size
    )
    return Page(
        items=channel_service.list_channel_reads(session, result),
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("/channels", response_model=ChannelRead, status_code=201, summary="新建渠道")
def create_channel(payload: ChannelCreate, session: DbSession, _: OperatorGuard) -> ChannelRead:
    channel = channel_service.create_channel(session, payload)
    return channel_service.to_channel_read(session, channel)


@router.get("/channels/{channel_id}", response_model=ChannelRead, summary="渠道详情")
def get_channel(channel_id: int, session: DbSession, _: ViewerGuard) -> ChannelRead:
    channel = channel_service.get_channel_or_404(session, channel_id)
    return channel_service.to_channel_read(session, channel)


@router.patch("/channels/{channel_id}", response_model=ChannelRead, summary="更新渠道")
def update_channel(
    channel_id: int, payload: ChannelUpdate, session: DbSession, _: OperatorGuard
) -> ChannelRead:
    channel = channel_service.get_channel_or_404(session, channel_id)
    channel = channel_service.update_channel(session, channel, payload)
    return channel_service.to_channel_read(session, channel)


# ----------------------------------------------------------------------- shop
@router.get(
    "/channels/{channel_id}/shops", response_model=list[ShopRead], summary="渠道下的店铺"
)
def list_shops(channel_id: int, session: DbSession, _: ViewerGuard) -> list[ShopRead]:
    shops = channel_service.list_shops(session, channel_id)
    return [channel_service.to_shop_read(shop) for shop in shops]


@router.post(
    "/channels/{channel_id}/shops",
    response_model=ShopRead,
    status_code=201,
    summary="新建店铺",
)
def create_shop(
    channel_id: int, payload: ShopCreate, session: DbSession, _: OperatorGuard
) -> ShopRead:
    shop = channel_service.create_shop(session, channel_id, payload)
    return channel_service.to_shop_read(shop)


# ----------------------------------------------------------- product mapping
@router.get(
    "/channel-products", response_model=Page[ChannelProductRead], summary="渠道商品映射列表"
)
def list_channel_products(
    session: DbSession,
    _: ViewerGuard,
    channel_id: int | None = None,
    sku_id: int | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[ChannelProductRead]:
    result = channel_repo.list_channel_products(
        session,
        channel_id=channel_id,
        sku_id=sku_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[channel_service.to_mapping_read(m) for m in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "/channel-products",
    response_model=ChannelProductRead,
    status_code=201,
    summary="新建渠道商品映射",
)
def create_channel_product(
    payload: ChannelProductCreate, session: DbSession, _: OperatorGuard
) -> ChannelProductRead:
    mapping = channel_service.create_mapping(session, payload)
    return channel_service.to_mapping_read(mapping)


@router.patch(
    "/channel-products/{mapping_id}", response_model=ChannelProductRead, summary="更新映射"
)
def update_channel_product(
    mapping_id: int, payload: ChannelProductUpdate, session: DbSession, _: OperatorGuard
) -> ChannelProductRead:
    mapping = channel_repo.get_channel_product(session, mapping_id)
    if mapping is None:
        raise BusinessError(CHANNEL_PRODUCT_NOT_FOUND, http_status=404)
    mapping = channel_service.update_mapping(session, mapping, payload)
    return channel_service.to_mapping_read(mapping)


@router.delete("/channel-products/{mapping_id}", status_code=204, summary="删除映射")
def delete_channel_product(mapping_id: int, session: DbSession, _: OperatorGuard) -> None:
    mapping = channel_repo.get_channel_product(session, mapping_id)
    if mapping is None:
        raise BusinessError(CHANNEL_PRODUCT_NOT_FOUND, http_status=404)
    channel_service.delete_mapping(session, mapping)
