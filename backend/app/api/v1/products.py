"""SPU, SKU and barcode endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.v1.guards import OperatorGuard, ViewerGuard
from app.core.deps import DbSession
from app.models.product import SkuStatus, SpuStatus, SpuType
from app.repositories import product_repo
from app.schemas.common import Page
from app.schemas.product import (
    BarcodeCreate,
    BarcodeRead,
    SkuCreateRequest,
    SkuRead,
    SkuUpdate,
    SpuCreate,
    SpuRead,
    SpuUpdate,
)
from app.services import product_service

router = APIRouter(tags=["products"])


# --------------------------------------------------------------------- SPU
@router.get("/spus", response_model=Page[SpuRead], summary="SPU 列表")
def list_spus(
    session: DbSession,
    _: ViewerGuard,
    keyword: str | None = None,
    status: SpuStatus | None = None,
    type: SpuType | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[SpuRead]:
    result = product_repo.list_spus(
        session, keyword=keyword, status=status, type_=type, page=page, page_size=page_size
    )
    return Page(
        items=product_service.list_spu_page(session, result),
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("/spus", response_model=SpuRead, status_code=201, summary="新建 SPU")
def create_spu(payload: SpuCreate, session: DbSession, _: OperatorGuard) -> SpuRead:
    spu = product_service.create_spu(session, payload)
    return product_service.to_spu_read(session, spu)


@router.get("/spus/{spu_id}", response_model=SpuRead, summary="SPU 详情")
def get_spu(spu_id: int, session: DbSession, _: ViewerGuard) -> SpuRead:
    spu = product_service.get_spu_or_404(session, spu_id)
    return product_service.to_spu_read(session, spu)


@router.patch("/spus/{spu_id}", response_model=SpuRead, summary="更新 SPU")
def update_spu(spu_id: int, payload: SpuUpdate, session: DbSession, _: OperatorGuard) -> SpuRead:
    spu = product_service.get_spu_or_404(session, spu_id)
    spu = product_service.update_spu(session, spu, payload)
    return product_service.to_spu_read(session, spu)


# --------------------------------------------------------------------- SKU
# ``/skus/resolve`` must be declared before ``/skus/{sku_id}`` so the literal
# path is not swallowed by the parameterised one.
@router.get("/skus/resolve", response_model=SkuRead, summary="按条码反查 SKU")
def resolve_sku(session: DbSession, _: ViewerGuard, barcode: str = Query(min_length=1)) -> SkuRead:
    return product_service.to_sku_read(product_service.resolve_barcode(session, barcode))


@router.get("/skus", response_model=Page[SkuRead], summary="SKU 列表")
def list_skus(
    session: DbSession,
    _: ViewerGuard,
    spu_id: int | None = None,
    keyword: str | None = None,
    status: SkuStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[SkuRead]:
    result = product_repo.list_skus(
        session, spu_id=spu_id, keyword=keyword, status=status, page=page, page_size=page_size
    )
    return Page(
        items=product_service.list_sku_page(session, result),
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("/skus", response_model=SkuRead, status_code=201, summary="新建 SKU")
def create_sku(payload: SkuCreateRequest, session: DbSession, _: OperatorGuard) -> SkuRead:
    # SkuCreateRequest is a SkuCreate plus the owning spu_id.
    sku = product_service.create_sku(session, payload.spu_id, payload)
    return product_service.to_sku_read(sku)


@router.get("/skus/{sku_id}", response_model=SkuRead, summary="SKU 详情")
def get_sku(sku_id: int, session: DbSession, _: ViewerGuard) -> SkuRead:
    sku = product_service.get_sku_or_404(session, sku_id)
    return product_service.to_sku_read(sku)


@router.patch("/skus/{sku_id}", response_model=SkuRead, summary="更新 SKU")
def update_sku(sku_id: int, payload: SkuUpdate, session: DbSession, _: OperatorGuard) -> SkuRead:
    sku = product_service.get_sku_or_404(session, sku_id)
    sku = product_service.update_sku(session, sku, payload)
    return product_service.to_sku_read(sku)


@router.get(
    "/skus/{sku_id}/barcodes", response_model=list[BarcodeRead], summary="SKU 条码列表"
)
def list_barcodes(sku_id: int, session: DbSession, _: ViewerGuard) -> list[BarcodeRead]:
    product_service.get_sku_or_404(session, sku_id)
    return [product_service.to_barcode_read(row) for row in product_repo.list_barcodes(session, sku_id)]


@router.post(
    "/skus/{sku_id}/barcodes", response_model=BarcodeRead, status_code=201, summary="新增条码"
)
def add_barcode(
    sku_id: int, payload: BarcodeCreate, session: DbSession, _: OperatorGuard
) -> BarcodeRead:
    row = product_service.add_barcode(session, sku_id, payload)
    return product_service.to_barcode_read(row)


@router.delete(
    "/skus/{sku_id}/barcodes/{barcode_id}", status_code=204, summary="删除条码"
)
def delete_barcode(sku_id: int, barcode_id: int, session: DbSession, _: OperatorGuard) -> None:
    product_service.delete_barcode(session, sku_id, barcode_id)
