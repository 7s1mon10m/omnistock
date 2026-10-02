"""Product schemas: SPU, SKU, barcodes and bundles."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.product import SkuStatus, SpuStatus, SpuType


# ------------------------------------------------------------------------ SPU
class SpuCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    category: str = Field(default="", max_length=64)
    brand: str = Field(default="", max_length=64)
    type: SpuType = SpuType.SINGLE
    images: list[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=1000)


class SpuUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    category: str | None = Field(default=None, max_length=64)
    brand: str | None = Field(default=None, max_length=64)
    images: list[str] | None = None
    description: str | None = Field(default=None, max_length=1000)
    status: SpuStatus | None = None


class SpuRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    category: str
    brand: str
    type: SpuType
    images: list[Any]
    description: str
    status: SpuStatus
    sku_count: int = 0
    created_at: dt.datetime | None = None


# ------------------------------------------------------------------------ SKU
class SkuCreate(BaseModel):
    # When omitted the service generates ``<SKU_CODE_PREFIX>-<spu_code>-<n>``.
    sku_code: str | None = Field(default=None, max_length=64)
    spec_json: dict[str, Any] = Field(default_factory=dict)
    barcode: str | None = Field(default=None, max_length=64)
    weight_g: int = Field(default=0, ge=0)
    package_spec: str = Field(default="", max_length=128)
    purchase_price_cents: int = Field(default=0, ge=0)
    default_supplier_id: int | None = None
    safety_qty: int = Field(default=0, ge=0)


class SkuCreateRequest(SkuCreate):
    """``POST /skus`` carries the owning SPU in the body."""

    spu_id: int


class SkuUpdate(BaseModel):
    spec_json: dict[str, Any] | None = None
    weight_g: int | None = Field(default=None, ge=0)
    package_spec: str | None = Field(default=None, max_length=128)
    purchase_price_cents: int | None = Field(default=None, ge=0)
    default_supplier_id: int | None = None
    safety_qty: int | None = Field(default=None, ge=0)
    status: SkuStatus | None = None


class SkuRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    spu_id: int
    sku_code: str
    display_name: str = ""
    spec_json: dict[str, Any]
    barcode: str | None
    weight_g: int
    package_spec: str
    purchase_price_cents: int
    default_supplier_id: int | None
    safety_qty: int
    status: SkuStatus
    is_bundle: bool = False
    created_at: dt.datetime | None = None


# ------------------------------------------------------------------- barcodes
class BarcodeCreate(BaseModel):
    barcode: str = Field(min_length=1, max_length=64)
    is_primary: bool = False
    remark: str = Field(default="", max_length=128)


class BarcodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku_id: int
    barcode: str
    is_primary: bool
    remark: str


# -------------------------------------------------------------------- bundles
class BundleComponentIn(BaseModel):
    component_sku_id: int
    quantity: int = Field(gt=0, le=10_000)


class BundleSetRequest(BaseModel):
    """Replace the whole component list of a bundle SKU in one call."""

    components: list[BundleComponentIn] = Field(min_length=1)


class BundleComponentRead(BaseModel):
    component_sku_id: int
    component_sku_code: str
    component_name: str
    quantity: int
    available_qty: int = 0


class BundleRead(BaseModel):
    bundle_sku_id: int
    bundle_sku_code: str
    bundle_name: str
    components: list[BundleComponentRead]
    # How many complete bundles the given warehouse could ship right now.
    buildable_qty: int = 0
