"""Inventory endpoints: read the aggregate, read the ledger, move stock.

No endpoint here ever sets a stock number directly.  ``/inventory/adjust`` and
``/inventory/reserve`` both go through the ledger, so every change is traceable.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.v1.guards import ViewerGuard, WarehouseGuard
from app.core.deps import DbSession
from app.models.inventory import InventoryTransactionType
from app.repositories import inventory_repo
from app.schemas.common import Page
from app.schemas.inventory import (
    BundleReserveRequest,
    InventoryAdjustRequest,
    InventoryReserveRequest,
    InventoryStockRead,
    InventoryTransactionRead,
)
from app.services import combo_service, inventory_service

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("", response_model=Page[InventoryStockRead], summary="库存总览（SKU × 仓库）")
def list_inventory(
    session: DbSession,
    _: ViewerGuard,
    sku_id: int | None = None,
    warehouse_id: int | None = None,
    keyword: str | None = None,
    low_only: bool = Query(False, description="只看可售 <= 0 的行"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[InventoryStockRead]:
    result = inventory_repo.list_stocks(
        session,
        sku_id=sku_id,
        warehouse_id=warehouse_id,
        keyword=keyword,
        low_only=low_only,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=inventory_service.list_stock_reads(session, result),
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get(
    "/ledger", response_model=Page[InventoryTransactionRead], summary="库存流水（只增不改）"
)
def list_ledger(
    session: DbSession,
    _: ViewerGuard,
    sku_id: int | None = None,
    warehouse_id: int | None = None,
    type: InventoryTransactionType | None = None,
    ref_type: str | None = None,
    ref_id: int | None = None,
    start: str | None = Query(None, description="YYYY-MM-DD 或 ISO 时间"),
    end: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[InventoryTransactionRead]:
    result = inventory_repo.list_transactions(
        session,
        sku_id=sku_id,
        warehouse_id=warehouse_id,
        type_=type,
        ref_type=ref_type,
        ref_id=ref_id,
        start=inventory_service.parse_dt(start),
        end=inventory_service.parse_dt(end),
        page=page,
        page_size=page_size,
    )
    return Page(
        items=inventory_service.list_transaction_reads(session, result),
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("/adjust", response_model=InventoryTransactionRead, summary="手工调整库存（必填原因）")
def adjust_inventory(
    payload: InventoryAdjustRequest, session: DbSession, user: WarehouseGuard
) -> InventoryTransactionRead:
    tx = inventory_service.adjust(session, payload, operator_id=user.id)
    return inventory_service.to_transaction_read(tx)


@router.post("/reserve", response_model=InventoryTransactionRead, summary="按 SKU 占用库存")
def reserve_inventory(
    payload: InventoryReserveRequest, session: DbSession, user: WarehouseGuard
) -> InventoryTransactionRead:
    tx = inventory_service.reserve(
        session,
        sku_id=payload.sku_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        ref_type=payload.ref_type,
        ref_id=payload.ref_id,
        operator_id=user.id,
        idempotency_key=payload.idempotency_key,
        remark=payload.remark,
    )
    session.commit()
    return inventory_service.to_transaction_read(tx)


@router.post("/release", response_model=InventoryTransactionRead, summary="释放已占用库存")
def release_inventory(
    payload: InventoryReserveRequest, session: DbSession, user: WarehouseGuard
) -> InventoryTransactionRead:
    tx = inventory_service.release(
        session,
        sku_id=payload.sku_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        ref_type=payload.ref_type,
        ref_id=payload.ref_id,
        operator_id=user.id,
        idempotency_key=payload.idempotency_key,
        remark=payload.remark,
    )
    session.commit()
    return inventory_service.to_transaction_read(tx)


@router.post(
    "/reserve-bundle",
    response_model=list[InventoryTransactionRead],
    summary="占用组合商品（自动拆解为子 SKU）",
)
def reserve_bundle(
    payload: BundleReserveRequest, session: DbSession, user: WarehouseGuard
) -> list[InventoryTransactionRead]:
    transactions = combo_service.reserve_bundle(
        session,
        bundle_sku_id=payload.bundle_sku_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        ref_type=payload.ref_type,
        ref_id=payload.ref_id,
        operator_id=user.id,
        idempotency_key=payload.idempotency_key,
    )
    session.commit()
    return [inventory_service.to_transaction_read(tx) for tx in transactions]
