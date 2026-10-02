"""Supplier data access."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.purchase import PurchaseOrder, PurchaseOrderStatus
from app.models.supplier import Supplier
from app.utils.pagination import PageResult, paginate

OPEN_ORDER_STATUSES = (
    PurchaseOrderStatus.DRAFT,
    PurchaseOrderStatus.SUBMITTED,
    PurchaseOrderStatus.PARTIAL,
)


def get(session: Session, supplier_id: int) -> Supplier | None:
    supplier = session.get(Supplier, supplier_id)
    if supplier is None or supplier.deleted_at is not None:
        return None
    return supplier


def get_by_code(session: Session, code: str) -> Supplier | None:
    stmt = select(Supplier).where(Supplier.code == code, Supplier.deleted_at.is_(None))
    return session.scalar(stmt)


def list_suppliers(
    session: Session,
    *,
    keyword: str | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(Supplier).where(Supplier.deleted_at.is_(None))
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                Supplier.code.like(pattern),
                Supplier.name.like(pattern),
                Supplier.contact_name.like(pattern),
            )
        )
    if is_active is not None:
        stmt = stmt.where(Supplier.is_active.is_(is_active))
    stmt = stmt.order_by(Supplier.id.desc())
    return paginate(session, stmt, page, page_size)


def create(session: Session, **fields) -> Supplier:
    supplier = Supplier(**fields)
    session.add(supplier)
    session.flush()
    return supplier


def count_open_orders(session: Session, supplier_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(PurchaseOrder)
        .where(
            PurchaseOrder.supplier_id == supplier_id,
            PurchaseOrder.status.in_(OPEN_ORDER_STATUSES),
            PurchaseOrder.deleted_at.is_(None),
        )
    )
    return session.scalar(stmt) or 0


def count_all(session: Session) -> int:
    stmt = select(func.count()).select_from(Supplier).where(Supplier.deleted_at.is_(None))
    return session.scalar(stmt) or 0
