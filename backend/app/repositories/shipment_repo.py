"""Data access for shipments, their pick lines and scan records."""

from __future__ import annotations

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.models.order import SalesOrder
from app.models.shipment import (
    PickRecord,
    Shipment,
    ShipmentItem,
    ShipmentStatus,
)
from app.utils.pagination import PageResult, paginate

#: Statuses that still count as "in flight" for one order.
ACTIVE_STATUSES = (
    ShipmentStatus.PENDING,
    ShipmentStatus.PICKING,
    ShipmentStatus.PICKED,
    ShipmentStatus.PACKED,
)


def get_shipment(session: Session, shipment_id: int) -> Shipment | None:
    return session.get(Shipment, shipment_id)


def get_active_by_order(session: Session, order_id: int) -> Shipment | None:
    """The in-flight shipment of an order, if any."""
    stmt = (
        select(Shipment)
        .where(Shipment.order_id == order_id, Shipment.status.in_(ACTIVE_STATUSES))
        .order_by(Shipment.id.desc())
    )
    return session.scalar(stmt)


def list_shipments(
    session: Session,
    *,
    status: ShipmentStatus | None = None,
    warehouse_id: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(Shipment).options(selectinload(Shipment.order))
    if status:
        stmt = stmt.where(Shipment.status == status)
    if warehouse_id:
        stmt = stmt.where(Shipment.warehouse_id == warehouse_id)
    if keyword:
        pattern = f"%{keyword}%"
        # Order numbers live on the sales order, so join to search them too.
        stmt = stmt.join(SalesOrder, SalesOrder.id == Shipment.order_id).where(
            or_(
                Shipment.shipment_no.like(pattern),
                SalesOrder.order_no.like(pattern),
                SalesOrder.channel_order_no.like(pattern),
            )
        )
    stmt = stmt.order_by(Shipment.id.desc())
    return paginate(session, stmt, page, page_size)


def create_shipment(session: Session, **fields) -> Shipment:
    shipment = Shipment(**fields)
    session.add(shipment)
    session.flush()
    return shipment


def create_item(session: Session, **fields) -> ShipmentItem:
    item = ShipmentItem(**fields)
    session.add(item)
    session.flush()
    return item


def next_shipment_no(session: Session, prefix: str, shipment_id: int) -> str:
    return f"{prefix}{shipment_id:08d}"


def count_pending_items(session: Session, shipment_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(ShipmentItem)
        .where(
            ShipmentItem.shipment_id == shipment_id,
            ShipmentItem.picked_qty < ShipmentItem.quantity,
        )
    )
    return session.scalar(stmt) or 0


def try_pick_atomic(session: Session, item_id: int, quantity: int) -> bool:
    """Add to a line's picked count, but never past what was ordered.

    Two scanners working the same line would otherwise both read
    ``picked_qty = 2`` and both write ``3``, quietly losing one scan — or worse,
    over-picking.  The ceiling lives in the WHERE clause instead.
    """
    stmt = (
        update(ShipmentItem)
        .where(
            ShipmentItem.id == item_id,
            ShipmentItem.picked_qty + quantity <= ShipmentItem.quantity,
        )
        .values(picked_qty=ShipmentItem.picked_qty + quantity)
        .execution_options(synchronize_session=False)
    )
    return (session.execute(stmt).rowcount or 0) > 0


# ------------------------------------------------------------------ pick log
def create_pick_record(session: Session, **fields) -> PickRecord:
    record = PickRecord(**fields)
    session.add(record)
    session.flush()
    return record


def list_pick_records(
    session: Session, *, shipment_id: int, page: int = 1, page_size: int = 50
) -> PageResult:
    stmt = (
        select(PickRecord)
        .where(PickRecord.shipment_id == shipment_id)
        .order_by(PickRecord.id.desc())
    )
    return paginate(session, stmt, page, page_size)
