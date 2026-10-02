"""Bundle (组合商品) endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.v1.guards import OperatorGuard, ViewerGuard
from app.core.deps import DbSession
from app.schemas.product import BundleRead, BundleSetRequest
from app.services import combo_service

router = APIRouter(prefix="/bundles", tags=["bundles"])


@router.get("/{bundle_sku_id}", response_model=BundleRead, summary="查看组合商品构成")
def get_bundle(
    bundle_sku_id: int,
    session: DbSession,
    _: ViewerGuard,
    warehouse_id: int | None = Query(default=None, description="给出仓库时可算出可组套数"),
) -> BundleRead:
    return combo_service.to_bundle_read(session, bundle_sku_id, warehouse_id)


@router.put(
    "/{bundle_sku_id}/components", response_model=BundleRead, summary="设置组合商品子项"
)
def set_components(
    bundle_sku_id: int,
    payload: BundleSetRequest,
    session: DbSession,
    _: OperatorGuard,
    warehouse_id: int | None = Query(default=None),
) -> BundleRead:
    combo_service.set_components(session, bundle_sku_id, payload)
    return combo_service.to_bundle_read(session, bundle_sku_id, warehouse_id)
