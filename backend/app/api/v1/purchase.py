"""Purchase order and goods-receipt endpoints.

Receipts live under their own prefix (``/purchase-receipts``) so the two routers
never compete for a path segment, and ``/purchase-orders`` has no literal
sibling routes to order around.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.v1.guards import BuyerGuard, ViewerGuard, WarehouseGuard
from app.core.deps import DbSession
from app.models.purchase import PurchaseOrderStatus
from app.repositories import purchase_repo
from app.schemas.common import Page
from app.schemas.purchase import (
    PurchaseOrderCreate,
    PurchaseOrderListRead,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
    ReceiptCreate,
    ReceiptRead,
    ReceiptResult,
)
from app.services import purchase_service

router = APIRouter(tags=["purchase"])


# ------------------------------------------------------------- purchase orders
@router.get(
    "/purchase-orders", response_model=Page[PurchaseOrderListRead], summary="采购单列表"
)
def list_purchase_orders(
    session: DbSession,
    _: ViewerGuard,
    supplier_id: int | None = None,
    warehouse_id: int | None = None,
    status: PurchaseOrderStatus | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[PurchaseOrderListRead]:
    result = purchase_repo.list_orders(
        session,
        supplier_id=supplier_id,
        warehouse_id=warehouse_id,
        status=status,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[purchase_service.to_list_read(order) for order in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post(
    "/purchase-orders", response_model=PurchaseOrderRead, status_code=201, summary="新建采购单"
)
def create_purchase_order(
    payload: PurchaseOrderCreate, session: DbSession, user: BuyerGuard
) -> PurchaseOrderRead:
    order = purchase_service.create_order(session, payload, buyer_id=user.id)
    return purchase_service.to_order_read(session, order)


@router.get(
    "/purchase-orders/{order_id}", response_model=PurchaseOrderRead, summary="采购单详情"
)
def get_purchase_order(order_id: int, session: DbSession, _: ViewerGuard) -> PurchaseOrderRead:
    order = purchase_service.get_order_or_404(session, order_id)
    return purchase_service.to_order_read(session, order)


@router.patch(
    "/purchase-orders/{order_id}", response_model=PurchaseOrderRead, summary="修改采购单（仅草稿）"
)
def update_purchase_order(
    order_id: int, payload: PurchaseOrderUpdate, session: DbSession, _: BuyerGuard
) -> PurchaseOrderRead:
    order = purchase_service.get_order_or_404(session, order_id)
    order = purchase_service.update_order(session, order, payload)
    return purchase_service.to_order_read(session, order)


@router.post(
    "/purchase-orders/{order_id}/submit",
    response_model=PurchaseOrderRead,
    summary="下单（草稿 → 待到货）",
)
def submit_purchase_order(
    order_id: int, session: DbSession, _: BuyerGuard
) -> PurchaseOrderRead:
    order = purchase_service.get_order_or_404(session, order_id)
    order = purchase_service.submit_order(session, order)
    return purchase_service.to_order_read(session, order)


@router.post(
    "/purchase-orders/{order_id}/cancel",
    response_model=PurchaseOrderRead,
    summary="取消采购单",
)
def cancel_purchase_order(
    order_id: int, session: DbSession, _: BuyerGuard, reason: str = ""
) -> PurchaseOrderRead:
    order = purchase_service.get_order_or_404(session, order_id)
    order = purchase_service.cancel_order(session, order, reason=reason)
    return purchase_service.to_order_read(session, order)


@router.post(
    "/purchase-orders/{order_id}/receipts",
    response_model=ReceiptResult,
    status_code=201,
    summary="登记到货（分批到货 + 质检分流）",
)
def create_receipt(
    order_id: int, payload: ReceiptCreate, session: DbSession, user: WarehouseGuard
) -> ReceiptResult:
    order = purchase_service.get_order_or_404(session, order_id)
    receipt = purchase_service.create_receipt(session, order, payload, operator_id=user.id)
    session.refresh(order)
    return ReceiptResult(
        receipt=purchase_service.to_receipt_read(session, receipt),
        order=purchase_service.to_order_read(session, order),
        message=(
            f"已收货 {receipt.total_quantity} 件"
            f"（合格 {receipt.total_quantity - receipt.total_defective} · "
            f"次品 {receipt.total_defective}）"
        ),
    )


# ------------------------------------------------------------------- receipts
@router.get("/purchase-receipts", response_model=Page[ReceiptRead], summary="收货单列表")
def list_receipts(
    session: DbSession,
    _: ViewerGuard,
    order_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[ReceiptRead]:
    result = purchase_repo.list_receipts(
        session, order_id=order_id, page=page, page_size=page_size
    )
    return Page(
        items=[purchase_service.to_receipt_read(session, row) for row in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/purchase-receipts/{receipt_id}", response_model=ReceiptRead, summary="收货单详情")
def get_receipt(receipt_id: int, session: DbSession, _: ViewerGuard) -> ReceiptRead:
    receipt = purchase_service.get_receipt_or_404(session, receipt_id)
    return purchase_service.to_receipt_read(session, receipt)
