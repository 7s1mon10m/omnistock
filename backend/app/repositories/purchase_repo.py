"""Purchase order and receipt data access."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.purchase import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    PurchaseReceipt,
    PurchaseReceiptItem,
)
from app.utils.pagination import PageResult, paginate


def get_order(session: Session, order_id: int) -> PurchaseOrder | None:
    order = session.get(PurchaseOrder, order_id)
    if order is None or order.deleted_at is not None:
        return None
    return order


def get_order_by_no(session: Session, po_no: str) -> PurchaseOrder | None:
    stmt = select(PurchaseOrder).where(
        PurchaseOrder.po_no == po_no, PurchaseOrder.deleted_at.is_(None)
    )
    return session.scalar(stmt)


def list_orders(
    session: Session,
    *,
    supplier_id: int | None = None,
    warehouse_id: int | None = None,
    status: PurchaseOrderStatus | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(PurchaseOrder).where(PurchaseOrder.deleted_at.is_(None))
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if warehouse_id:
        stmt = stmt.where(PurchaseOrder.warehouse_id == warehouse_id)
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            or_(PurchaseOrder.po_no.like(pattern), PurchaseOrder.remark.like(pattern))
        )
    stmt = stmt.order_by(PurchaseOrder.id.desc())
    return paginate(session, stmt, page, page_size)


def create_order(session: Session, **fields) -> PurchaseOrder:
    order = PurchaseOrder(**fields)
    session.add(order)
    session.flush()
    return order


def create_item(session: Session, **fields) -> PurchaseOrderItem:
    item = PurchaseOrderItem(**fields)
    session.add(item)
    session.flush()
    return item


def delete_items(session: Session, order_id: int) -> None:
    for item in session.scalars(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id)
    ).all():
        session.delete(item)
    session.flush()


def next_order_no(session: Session, prefix: str, order_id: int) -> str:
    return f"{prefix}{order_id:08d}"


# -------------------------------------------------------------------- receipts
def create_receipt(session: Session, **fields) -> PurchaseReceipt:
    receipt = PurchaseReceipt(**fields)
    session.add(receipt)
    session.flush()
    return receipt


def create_receipt_item(session: Session, **fields) -> PurchaseReceiptItem:
    item = PurchaseReceiptItem(**fields)
    session.add(item)
    session.flush()
    return item


def get_receipt(session: Session, receipt_id: int) -> PurchaseReceipt | None:
    return session.get(PurchaseReceipt, receipt_id)


def list_receipts(
    session: Session, *, order_id: int | None = None, page: int = 1, page_size: int = 20
) -> PageResult:
    stmt = select(PurchaseReceipt).options(
        selectinload(PurchaseReceipt.order), selectinload(PurchaseReceipt.items)
    )
    if order_id:
        stmt = stmt.where(PurchaseReceipt.order_id == order_id)
    stmt = stmt.order_by(PurchaseReceipt.id.desc())
    return paginate(session, stmt, page, page_size)


def list_receipts_for_order(session: Session, order_id: int) -> list[PurchaseReceipt]:
    stmt = (
        select(PurchaseReceipt)
        .where(PurchaseReceipt.order_id == order_id)
        .order_by(PurchaseReceipt.id)
    )
    return list(session.scalars(stmt).all())


def next_receipt_no(session: Session, prefix: str, receipt_id: int) -> str:
    return f"{prefix}{receipt_id:08d}"
