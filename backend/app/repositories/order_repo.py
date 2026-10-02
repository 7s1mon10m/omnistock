"""Data access for orders, their items, exceptions and sync logs."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.inventory import InventoryTransaction, InventoryTransactionType
from app.models.order import (
    ExceptionStatus,
    ExceptionType,
    ImportBatch,
    OrderException,
    OrderStatus,
    OrderSyncLog,
    SalesOrder,
    SalesOrderItem,
    SyncResult,
)
from app.utils.pagination import PageResult, paginate

#: Ledger types that describe stock held *for* an order.
#: ``order_reserve`` adds to the hold; ``order_release`` (cancellation) and
#: ``order_outbound`` (shipping) both take away from it — so summing the three
#: gives what the order is still holding right now.
RESERVATION_TYPES = (
    InventoryTransactionType.ORDER_RESERVE,
    InventoryTransactionType.ORDER_RELEASE,
    InventoryTransactionType.ORDER_OUTBOUND,
)


# ---------------------------------------------------------------------- order
def get_order(session: Session, order_id: int) -> SalesOrder | None:
    order = session.get(SalesOrder, order_id)
    if order is None or order.deleted_at is not None:
        return None
    return order


def get_order_by_channel_no(
    session: Session, channel_id: int, channel_order_no: str
) -> SalesOrder | None:
    stmt = select(SalesOrder).where(
        SalesOrder.channel_id == channel_id,
        SalesOrder.channel_order_no == channel_order_no,
        SalesOrder.deleted_at.is_(None),
    )
    return session.scalar(stmt)


def list_orders(
    session: Session,
    *,
    channel_id: int | None = None,
    status: OrderStatus | None = None,
    keyword: str | None = None,
    only_exception: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(SalesOrder).where(SalesOrder.deleted_at.is_(None))
    if channel_id:
        stmt = stmt.where(SalesOrder.channel_id == channel_id)
    if status:
        stmt = stmt.where(SalesOrder.status == status)
    if only_exception:
        stmt = stmt.where(SalesOrder.status == OrderStatus.EXCEPTION)
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                SalesOrder.order_no.like(pattern),
                SalesOrder.channel_order_no.like(pattern),
                SalesOrder.buyer_nick.like(pattern),
            )
        )
    stmt = stmt.order_by(SalesOrder.id.desc())
    return paginate(session, stmt, page, page_size)


def create_order(session: Session, **fields) -> SalesOrder:
    order = SalesOrder(**fields)
    session.add(order)
    session.flush()
    return order


def create_item(session: Session, **fields) -> SalesOrderItem:
    item = SalesOrderItem(**fields)
    session.add(item)
    session.flush()
    return item


def next_order_no(session: Session, prefix: str, order_id: int) -> str:
    return f"{prefix}{order_id:08d}"


def net_reservations(session: Session, order_id: int) -> list[tuple[int, int, int]]:
    """``[(sku_id, warehouse_id, qty), ...]`` currently held for this order.

    Derived straight from the ledger: reservations are positive ledger rows and
    releases are negative ones, so the sum is what is still held.  This stays
    correct even if the bundle definition changes later.
    """
    stmt = (
        select(
            InventoryTransaction.sku_id,
            InventoryTransaction.warehouse_id,
            func.sum(InventoryTransaction.qty_delta).label("qty"),
        )
        .where(
            InventoryTransaction.ref_type == "sales_order",
            InventoryTransaction.ref_id == order_id,
            InventoryTransaction.type.in_(RESERVATION_TYPES),
        )
        .group_by(InventoryTransaction.sku_id, InventoryTransaction.warehouse_id)
    )
    rows = session.execute(stmt).all()
    return [(row[0], row[1], int(row[2] or 0)) for row in rows if int(row[2] or 0) > 0]


# ---------------------------------------------------------------- exceptions
def create_exception(session: Session, **fields) -> OrderException:
    exc = OrderException(**fields)
    session.add(exc)
    session.flush()
    return exc


def list_exceptions(
    session: Session,
    *,
    status: ExceptionStatus | None = None,
    type_: ExceptionType | None = None,
    order_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(OrderException).options(
        selectinload(OrderException.order), selectinload(OrderException.sku)
    )
    if status:
        stmt = stmt.where(OrderException.status == status)
    if type_:
        stmt = stmt.where(OrderException.type == type_)
    if order_id:
        stmt = stmt.where(OrderException.order_id == order_id)
    stmt = stmt.order_by(OrderException.id.desc())
    return paginate(session, stmt, page, page_size)


def count_open_exceptions(session: Session, order_id: int) -> int:
    stmt = select(func.count()).select_from(OrderException).where(
        OrderException.order_id == order_id, OrderException.status == ExceptionStatus.OPEN
    )
    return session.scalar(stmt) or 0


def resolve_open_exceptions(
    session: Session, order_id: int, *, status: ExceptionStatus, resolved_by: int | None = None
) -> int:
    """Close every open exception of an order; returns how many were closed."""
    rows = session.scalars(
        select(OrderException).where(
            OrderException.order_id == order_id,
            OrderException.status == ExceptionStatus.OPEN,
        )
    ).all()
    from app.models.base import utcnow

    for row in rows:
        row.status = status
        row.resolved_at = utcnow()
        row.resolved_by = resolved_by
    session.flush()
    return len(rows)


# ----------------------------------------------------------------- sync logs
def create_sync_log(session: Session, **fields) -> OrderSyncLog:
    log = OrderSyncLog(**fields)
    session.add(log)
    session.flush()
    return log


def list_sync_logs(
    session: Session,
    *,
    channel_id: int | None = None,
    channel_order_no: str | None = None,
    result: SyncResult | None = None,
    batch_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(OrderSyncLog).options(selectinload(OrderSyncLog.channel))
    if channel_id:
        stmt = stmt.where(OrderSyncLog.channel_id == channel_id)
    if channel_order_no:
        stmt = stmt.where(OrderSyncLog.channel_order_no.like(f"%{channel_order_no}%"))
    if result:
        stmt = stmt.where(OrderSyncLog.result == result)
    if batch_id:
        stmt = stmt.where(OrderSyncLog.batch_id == batch_id)
    stmt = stmt.order_by(OrderSyncLog.id.desc())
    return paginate(session, stmt, page, page_size)


# -------------------------------------------------------------- import batch
def create_import_batch(session: Session, **fields) -> ImportBatch:
    batch = ImportBatch(**fields)
    session.add(batch)
    session.flush()
    return batch


def get_import_batch(session: Session, batch_id: int) -> ImportBatch | None:
    return session.get(ImportBatch, batch_id)


def list_import_batches(
    session: Session, *, page: int = 1, page_size: int = 20
) -> PageResult:
    stmt = select(ImportBatch).order_by(ImportBatch.id.desc())
    return paginate(session, stmt, page, page_size)
