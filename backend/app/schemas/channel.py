"""Channel, shop and channel-product mapping schemas."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.models.channel import ChannelPlatform


# -------------------------------------------------------------------- channel
class ChannelCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    platform: ChannelPlatform = ChannelPlatform.OTHER
    remark: str = Field(default="", max_length=255)


class ChannelUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    platform: ChannelPlatform | None = None
    is_active: bool | None = None
    remark: str | None = Field(default=None, max_length=255)


class ChannelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    platform: ChannelPlatform
    is_active: bool
    remark: str
    shop_count: int = 0
    product_count: int = 0
    created_at: dt.datetime | None = None


# ----------------------------------------------------------------------- shop
class ShopCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(default="", max_length=64)
    remark: str = Field(default="", max_length=255)


class ShopRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_id: int
    code: str
    name: str
    is_active: bool
    remark: str


# ----------------------------------------------------------- product mapping
class ChannelProductCreate(BaseModel):
    channel_id: int
    shop_id: int | None = None
    channel_product_code: str = Field(min_length=1, max_length=64)
    sku_id: int
    channel_title: str = Field(default="", max_length=255)
    remark: str = Field(default="", max_length=255)


class ChannelProductUpdate(BaseModel):
    shop_id: int | None = None
    sku_id: int | None = None
    channel_title: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    remark: str | None = Field(default=None, max_length=255)


class ChannelProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_id: int
    channel_code: str = ""
    channel_name: str = ""
    shop_id: int | None = None
    shop_code: str = ""
    channel_product_code: str
    sku_id: int
    sku_code: str = ""
    sku_name: str = ""
    channel_title: str
    is_active: bool
    remark: str
    created_at: dt.datetime | None = None
