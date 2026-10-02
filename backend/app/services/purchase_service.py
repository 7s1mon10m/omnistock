"""Purchase order and goods-receipt services.

Two rules shape everything here:

* **A purchase order never changes stock.** Only a receipt does.  Submitting an
  order is a promise; receiving is the event.
* **A receipt always splits qualified from defective.** The qualified part raises
  on-hand (and therefore sellable stock); the defective part goes to the
  defective bucket and never becomes sellable.  Collapsing the two would make
  "on hand" a lie.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    PURCHASE_ITEM_NOT_FOUND,
    PURCHASE_ORDER_NOT_FOUND,
    PURCHASE_ORDER_NO_ITEMS,
    PURCHASE_ORDER_STATUS_INVALID,
    RECEIPT_QUANTITY_EXCEEDS,
    RECEIPT_QUANTITY_INVALID,
    SKU_NOT_FOUND,
    SUPPLIER_NOT_FOUND,
    WAREHOUSE_NOT_FOUND,
    BusinessError,
)
from app.models.base import utcnow
from app.models.purchase import (
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchaseReceipt,
    ReceiptStatus,
)
from app.repositories import (
    inventory_repo,
    product_repo,
    purchase_repo,
    supplier_repo,
    user_repo,
    warehouse_repo,
)
from app.schemas.purchase import (
    PurchaseItemRead,
    PurchaseOrderCreate,
    PurchaseOrderListRead,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
    ReceiptBrief,
    ReceiptItemRead,
    ReceiptRead,
)
from app.services import inventory_service

LEDGER_REF = "purchase_receipt"


# ------------------------------------------------------------------- lookups
def get_order_or_404(session: Session, order_id: int) -> PurchaseOrder:
    order = purchase_repo.get_order(session, order_id)
    if order is None:
        raise BusinessError(PURCHASE_ORDER_NOT_FOUND, http_status=404)
    return order


def get_receipt_or_404(session: Session, receipt_id: int) -> PurchaseReceipt:
    receipt = purchase_repo.get_receipt(session, receipt_id)
    if receipt is None:
        raise BusinessError(40453, http_status=404)
    return receipt


def _user_name(session: Session, user_id: int | None) -> str:
    if not user_id:
        return ""
    user = user_repo.get(session, user_id)
    return (user.full_name or user.username) if user else ""


# -------------------------------------------------------------------- orders
def create_order(
    session: Session, payload: PurchaseOrderCreate, *, buyer_id: int | None = None
) -> PurchaseOrder:
    supplier = supplier_repo.get(session, payload.supplier_id)
    if supplier is None:
        raise BusinessError(SUPPLIER_NOT_FOUND, http_status=404)
    if warehouse_repo.get(session, payload.warehouse_id) is None:
        raise BusinessError(WAREHOUSE_NOT_FOUND, http_status=404)
    if not payload.items:
        raise BusinessError(PURCHASE_ORDER_NO_ITEMS, http_status=400)

    total = 0
    order = purchase_repo.create_order(
        session,
        supplier_id=supplier.id,
        warehouse_id=payload.warehouse_id,
        status=PurchaseOrderStatus.DRAFT,
        expected_at=payload.expected_at
        or _default_expected_at(supplier.lead_time_days),
        buyer_id=buyer_id,
        remark=payload.remark,
    )
    order.po_no = purchase_repo.next_order_no(session, settings.PURCHASE_ORDER_PREFIX, order.id)

    for line_no, item in enumerate(payload.items, start=1):
        if product_repo.get_sku(session, item.sku_id) is None:
            raise BusinessError(SKU_NOT_FOUND, detail={"sku_id": item.sku_id}, http_status=404)
        purchase_repo.create_item(
            session,
            order_id=order.id,
            line_no=line_no,
            sku_id=item.sku_id,
            quantity=item.quantity,
            unit_price_cents=item.unit_price_cents,
            remark=item.remark,
        )
        total += item.quantity * item.unit_price_cents

    order.total_amount_cents = total
    session.commit()
    session.refresh(order)
    return order


def _default_expected_at(lead_time_days: int) -> dt.datetime:
    return utcnow() + dt.timedelta(days=max(0, lead_time_days))


def update_order(
    session: Session, order: PurchaseOrder, payload: PurchaseOrderUpdate
) -> PurchaseOrder:
    if order.status != PurchaseOrderStatus.DRAFT:
        raise BusinessError(
            PURCHASE_ORDER_STATUS_INVALID,
            f"只有草稿状态的采购单可以修改，当前为 {order.status.value}",
            http_status=409,
        )

    changes = payload.model_dump(exclude_unset=True)
    if changes.get("expected_at") is not None:
        order.expected_at = changes["expected_at"]
    if changes.get("remark") is not None:
        order.remark = changes["remark"]
    if changes.get("items") is not None:
        items = payload.items or []
        if not items:
            raise BusinessError(PURCHASE_ORDER_NO_ITEMS, http_status=400)
        purchase_repo.delete_items(session, order.id)
        total = 0
        for line_no, item in enumerate(items, start=1):
            if product_repo.get_sku(session, item.sku_id) is None:
                raise BusinessError(SKU_NOT_FOUND, detail={"sku_id": item.sku_id}, http_status=404)
            purchase_repo.create_item(
                session,
                order_id=order.id,
                line_no=line_no,
                sku_id=item.sku_id,
                quantity=item.quantity,
                unit_price_cents=item.unit_price_cents,
                remark=item.remark,
            )
            total += item.quantity * item.unit_price_cents
        order.total_amount_cents = total

    session.commit()
    session.refresh(order)
    return order


def submit_order(session: Session, order: PurchaseOrder) -> PurchaseOrder:
    """草稿 → 已下单。真正开始等货。"""
    if order.status != PurchaseOrderStatus.DRAFT:
        raise BusinessError(
            PURCHASE_ORDER_STATUS_INVALID,
            f"当前状态 {order.status.value} 不能下单",
            http_status=409,
        )
    if not order.items:
        raise BusinessError(PURCHASE_ORDER_NO_ITEMS, http_status=400)

    order.status = PurchaseOrderStatus.SUBMITTED
    order.ordered_at = utcnow()
    session.commit()
    return order


def cancel_order(session: Session, order: PurchaseOrder, *, reason: str = "") -> PurchaseOrder:
    if order.status not in (
        PurchaseOrderStatus.DRAFT,
        PurchaseOrderStatus.SUBMITTED,
        PurchaseOrderStatus.PARTIAL,
    ):
        raise BusinessError(
            PURCHASE_ORDER_STATUS_INVALID,
            f"当前状态 {order.status.value} 不能取消",
            http_status=409,
        )
    order.status = PurchaseOrderStatus.CANCELLED
    if reason:
        order.remark = f"{order.remark} | 取消：{reason}"[:255]
    session.commit()
    return order


# ------------------------------------------------------------------- receipts
def create_receipt(
    session: Session,
    order: PurchaseOrder,
    payload,
    *,
    operator_id: int | None = None,
) -> PurchaseReceipt:
    """登记一次到货，并按质检结果入库。"""
    if order.status not in (PurchaseOrderStatus.SUBMITTED, PurchaseOrderStatus.PARTIAL):
        raise BusinessError(
            PURCHASE_ORDER_STATUS_INVALID,
            f"当前状态 {order.status.value} 不能收货",
            http_status=409,
        )
    if not payload.items:
        raise BusinessError(RECEIPT_QUANTITY_INVALID, "收货明细不能为空", http_status=400)

    items_by_id = {item.id: item for item in order.items}

    # 先整体校验，避免写了一半才发现某一行超收。
    planned: list[tuple[int, int, int, int | None]] = []
    for line in payload.items:
        item = items_by_id.get(line.order_item_id)
        if item is None:
            raise BusinessError(
                PURCHASE_ITEM_NOT_FOUND,
                detail={"order_item_id": line.order_item_id},
                http_status=404,
            )
        if line.defective_qty > line.quantity:
            raise BusinessError(RECEIPT_QUANTITY_INVALID, http_status=400)

        if settings.PURCHASE_OVER_RECEIPT_PERCENT > 0:
            ceiling = item.quantity * (100 + settings.PURCHASE_OVER_RECEIPT_PERCENT) // 100
        else:
            ceiling = item.quantity
        if item.received_qty + line.quantity > ceiling:
            raise BusinessError(
                RECEIPT_QUANTITY_EXCEEDS,
                f"{item.sku.sku_code if item.sku else item.sku_id} 本次到货 {line.quantity} 件，"
                f"但最多还能收 {max(0, ceiling - item.received_qty)} 件",
                detail={
                    "order_item_id": item.id,
                    "ordered": item.quantity,
                    "received": item.received_qty,
                    "this_receipt": line.quantity,
                },
                http_status=409,
            )
        planned.append((item.id, line.quantity, line.defective_qty, line.location_id))

    receipt = purchase_repo.create_receipt(
        session,
        order_id=order.id,
        warehouse_id=order.warehouse_id,
        status=ReceiptStatus.POSTED,
        received_by=operator_id,
        received_at=utcnow(),
        remark=payload.remark,
    )
    receipt.receipt_no = purchase_repo.next_receipt_no(
        session, settings.PURCHASE_RECEIPT_PREFIX, receipt.id
    )

    for order_item_id, quantity, defective_qty, location_id in planned:
        item = items_by_id[order_item_id]
        purchase_repo.create_receipt_item(
            session,
            receipt_id=receipt.id,
            order_item_id=item.id,
            sku_id=item.sku_id,
            location_id=location_id,
            quantity=quantity,
            defective_qty=defective_qty,
        )

        inventory_service.receive_purchase(
            session,
            sku_id=item.sku_id,
            warehouse_id=order.warehouse_id,
            qualified_qty=quantity - defective_qty,
            defective_qty=defective_qty,
            location_id=location_id,
            ref_type=LEDGER_REF,
            ref_id=receipt.id,
            operator_id=operator_id,
            remark=f"采购入库 {receipt.receipt_no}",
            idempotency_key=f"receipt:{receipt.id}:{item.sku_id}",
        )

        item.received_qty += quantity
        item.defective_qty += defective_qty

    # 收齐了就结单，否则标记为部分到货。
    refreshed = [items_by_id[item.id] for item in order.items]
    order.status = (
        PurchaseOrderStatus.RECEIVED
        if all(row.received_qty >= row.quantity for row in refreshed)
        else PurchaseOrderStatus.PARTIAL
    )
    session.commit()
    session.refresh(receipt)
    return receipt


# ----------------------------------------------------------------- read views
def to_item_read(item) -> PurchaseItemRead:
    sku = item.sku
    return PurchaseItemRead(
        id=item.id,
        line_no=item.line_no,
        sku_id=item.sku_id,
        sku_code=sku.sku_code if sku else "",
        sku_name=sku.display_name if sku else "",
        quantity=item.quantity,
        received_qty=item.received_qty,
        defective_qty=item.defective_qty,
        outstanding_qty=item.outstanding_qty,
        unit_price_cents=item.unit_price_cents,
        remark=item.remark,
    )


def to_order_read(session: Session, order: PurchaseOrder) -> PurchaseOrderRead:
    supplier = order.supplier
    warehouse = order.warehouse
    return PurchaseOrderRead(
        id=order.id,
        po_no=order.po_no,
        supplier_id=order.supplier_id,
        supplier_code=supplier.code if supplier else "",
        supplier_name=supplier.name if supplier else "",
        warehouse_id=order.warehouse_id,
        warehouse_code=warehouse.code if warehouse else "",
        warehouse_name=warehouse.name if warehouse else "",
        status=order.status,
        ordered_at=order.ordered_at,
        expected_at=order.expected_at,
        total_amount_cents=order.total_amount_cents,
        total_quantity=order.total_quantity,
        received_quantity=order.received_quantity,
        is_fully_received=order.is_fully_received,
        buyer_id=order.buyer_id,
        buyer_name=_user_name(session, order.buyer_id),
        remark=order.remark,
        items=[to_item_read(item) for item in sorted(order.items, key=lambda row: row.line_no)],
        receipts=[
            ReceiptBrief(
                id=row.id,
                receipt_no=row.receipt_no,
                status=row.status,
                total_quantity=row.total_quantity,
                total_defective=row.total_defective,
                received_at=row.received_at,
            )
            for row in purchase_repo.list_receipts_for_order(session, order.id)
        ],
        created_at=order.created_at,
    )


def to_list_read(order: PurchaseOrder) -> PurchaseOrderListRead:
    supplier = order.supplier
    warehouse = order.warehouse
    return PurchaseOrderListRead(
        id=order.id,
        po_no=order.po_no,
        supplier_name=supplier.name if supplier else "",
        warehouse_code=warehouse.code if warehouse else "",
        status=order.status,
        total_quantity=order.total_quantity,
        received_quantity=order.received_quantity,
        total_amount_cents=order.total_amount_cents,
        expected_at=order.expected_at,
        created_at=order.created_at,
    )


def to_receipt_read(session: Session, receipt: PurchaseReceipt) -> ReceiptRead:
    order = receipt.order
    warehouse = receipt.warehouse
    return ReceiptRead(
        id=receipt.id,
        receipt_no=receipt.receipt_no,
        order_id=receipt.order_id,
        po_no=order.po_no if order else "",
        warehouse_id=receipt.warehouse_id,
        warehouse_code=warehouse.code if warehouse else "",
        status=receipt.status,
        received_by=receipt.received_by,
        received_by_name=_user_name(session, receipt.received_by),
        received_at=receipt.received_at,
        total_quantity=receipt.total_quantity,
        total_defective=receipt.total_defective,
        remark=receipt.remark,
        items=[
            ReceiptItemRead(
                id=row.id,
                order_item_id=row.order_item_id,
                sku_id=row.sku_id,
                sku_code=row.sku.sku_code if row.sku else "",
                sku_name=row.sku.display_name if row.sku else "",
                quantity=row.quantity,
                defective_qty=row.defective_qty,
                qualified_qty=row.qualified_qty,
                location_id=row.location_id,
                location_code=row.location.code if row.location else "",
                remark=row.remark,
            )
            for row in receipt.items
        ],
        created_at=receipt.created_at,
    )


def stock_snapshot(session: Session, order: PurchaseOrder) -> list[dict]:
    """Where the received goods actually landed — handy for the receipt response."""
    rows = []
    for item in order.items:
        stock = inventory_repo.get_stock(session, item.sku_id, order.warehouse_id)
        if stock is None:
            continue
        rows.append(
            {
                "sku_id": item.sku_id,
                "on_hand": stock.on_hand_qty,
                "defective": stock.defective_qty,
                "available": stock.available_qty,
            }
        )
    return rows
