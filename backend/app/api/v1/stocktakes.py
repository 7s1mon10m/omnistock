"""Stocktakes: counting, submission and variance approval."""

from __future__ import annotations

from fastapi import APIRouter, Body, Query

from app.api.v1.guards import AdminGuard, ViewerGuard, WarehouseGuard
from app.core.deps import DbSession
from app.models.stocktake import StocktakeStatus
from app.repositories import stocktake_repo
from app.schemas.common import Page
from app.schemas.stocktake import (
    StocktakeCountRequest,
    StocktakeCreate,
    StocktakeListRead,
    StocktakeRead,
    StocktakeScanRequest,
)
from app.services import stocktake_service

router = APIRouter(prefix="/stocktakes", tags=["stocktakes"])


@router.get("", response_model=Page[StocktakeListRead], summary="盘点单列表")
def list_stocktakes(
    session: DbSession,
    _: ViewerGuard,
    status: StocktakeStatus | None = None,
    warehouse_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[StocktakeListRead]:
    result = stocktake_repo.list_stocktakes(
        session, status=status, warehouse_id=warehouse_id, page=page, page_size=page_size
    )
    return Page(
        items=[stocktake_service.to_list_read(row) for row in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("", response_model=StocktakeRead, status_code=201, summary="发起盘点")
def create_stocktake(
    payload: StocktakeCreate, session: DbSession, user: WarehouseGuard
) -> StocktakeRead:
    return stocktake_service.to_read(
        session, stocktake_service.create(session, payload, operator_id=user.id)
    )


@router.get("/{stocktake_id}", response_model=StocktakeRead, summary="盘点单详情")
def get_stocktake(stocktake_id: int, session: DbSession, _: ViewerGuard) -> StocktakeRead:
    return stocktake_service.to_read(
        session, stocktake_service.get_or_404(session, stocktake_id)
    )


@router.post("/{stocktake_id}/counts", response_model=StocktakeRead, summary="批量录入实盘数")
def count_stocktake(
    stocktake_id: int,
    payload: StocktakeCountRequest,
    session: DbSession,
    user: WarehouseGuard,
) -> StocktakeRead:
    stocktake = stocktake_service.get_or_404(session, stocktake_id)
    return stocktake_service.to_read(
        session, stocktake_service.count(session, stocktake, payload, operator_id=user.id)
    )


@router.post("/{stocktake_id}/scan", response_model=StocktakeRead, summary="扫码录入实盘数")
def scan_stocktake(
    stocktake_id: int, payload: StocktakeScanRequest, session: DbSession, user: WarehouseGuard
) -> StocktakeRead:
    """按条码定位盘点行，省掉在清单里找 SKU 这一步。"""
    stocktake = stocktake_service.get_or_404(session, stocktake_id)
    from app.core.errors import STOCKTAKE_LINE_NOT_FOUND, BusinessError
    from app.services import product_service

    sku = product_service.resolve_barcode(session, payload.barcode)
    if sku is None:
        raise BusinessError(STOCKTAKE_LINE_NOT_FOUND, f"条码 {payload.barcode} 未识别", http_status=404)

    item = next((row for row in stocktake.items if row.sku_id == sku.id), None)
    if item is None:
        raise BusinessError(
            STOCKTAKE_LINE_NOT_FOUND,
            f"{sku.sku_code} 不在本次盘点范围内",
            http_status=404,
        )

    request = StocktakeCountRequest(
        items=[{"stocktake_item_id": item.id, "counted_qty": payload.counted_qty}]
    )
    return stocktake_service.to_read(
        session, stocktake_service.count(session, stocktake, request, operator_id=user.id)
    )


@router.post("/{stocktake_id}/submit", response_model=StocktakeRead, summary="提交盘点")
def submit_stocktake(stocktake_id: int, session: DbSession, user: WarehouseGuard) -> StocktakeRead:
    stocktake = stocktake_service.get_or_404(session, stocktake_id)
    return stocktake_service.to_read(
        session, stocktake_service.submit(session, stocktake, operator_id=user.id)
    )


@router.post("/{stocktake_id}/approve", response_model=StocktakeRead, summary="审核并落账")
def approve_stocktake(
    stocktake_id: int,
    session: DbSession,
    user: AdminGuard,
    remark: str = Body(default="", embed=True),
) -> StocktakeRead:
    stocktake = stocktake_service.get_or_404(session, stocktake_id)
    return stocktake_service.to_read(
        session, stocktake_service.approve(session, stocktake, operator_id=user.id, remark=remark)
    )


@router.post("/{stocktake_id}/cancel", response_model=StocktakeRead, summary="取消盘点（未审核）")
def cancel_stocktake(
    stocktake_id: int,
    session: DbSession,
    _: WarehouseGuard,
    reason: str = Body(default="", embed=True),
) -> StocktakeRead:
    stocktake = stocktake_service.get_or_404(session, stocktake_id)
    return stocktake_service.to_read(session, stocktake_service.cancel(session, stocktake, reason=reason))
