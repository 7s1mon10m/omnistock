"""Data access for inventory aggregates and the append-only ledger.

The lock helper is the heart of oversell protection: on PostgreSQL
``with_for_update`` takes a row lock so two concurrent order confirmations are
serialised.  SQLite ignores the clause, which is fine because the test suite
exercises the same code path through a single connection.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.models.inventory import InventoryStock, InventoryTransaction, InventoryTransactionType
from app.models.product import Sku
from app.models.user import User
from app.models.warehouse import Warehouse
from app.utils.pagination import PageResult, paginate


# ---------------------------------------------------------------------- stock
def get_stock(session: Session, sku_id: int, warehouse_id: int) -> InventoryStock | None:
    stmt = select(InventoryStock).where(
        InventoryStock.sku_id == sku_id, InventoryStock.warehouse_id == warehouse_id
    )
    return session.scalar(stmt)


def lock_stock(session: Session, sku_id: int, warehouse_id: int) -> InventoryStock | None:
    """Fetch a stock row holding a write lock until the transaction ends.

    Callers must already have a transaction open.  Using this everywhere stock
    is *decremented* is what makes the "先到先得" rule hold under concurrency.
    """
    stmt = (
        select(InventoryStock)
        .where(InventoryStock.sku_id == sku_id, InventoryStock.warehouse_id == warehouse_id)
        .with_for_update()
    )
    return session.scalar(stmt)


def create_stock(
    session: Session, *, sku_id: int, warehouse_id: int, safety_qty: int = 0
) -> InventoryStock:
    stock = InventoryStock(sku_id=sku_id, warehouse_id=warehouse_id, safety_qty=safety_qty)
    session.add(stock)
    session.flush()
    return stock


def try_reserve_atomic(session: Session, sku_id: int, warehouse_id: int, quantity: int) -> bool:
    """Reserve ``quantity`` only if sellable stock still allows it.

    This is a conditional ``UPDATE``: the database re-evaluates the WHERE clause
    against committed data while holding the row's write lock, so two concurrent
    buyers can never both see the same "available" number.  Works on SQLite as
    well as PostgreSQL, unlike a plain read-then-write.
    """
    sellable = (
        InventoryStock.on_hand_qty - InventoryStock.reserved_qty - InventoryStock.safety_qty
    )
    stmt = (
        update(InventoryStock)
        .where(
            InventoryStock.sku_id == sku_id,
            InventoryStock.warehouse_id == warehouse_id,
            sellable >= quantity,
        )
        .values(
            reserved_qty=InventoryStock.reserved_qty + quantity,
            version=InventoryStock.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    result = session.execute(stmt)
    return (result.rowcount or 0) > 0


def try_release_atomic(session: Session, sku_id: int, warehouse_id: int, quantity: int) -> bool:
    """Give back occupied stock, but never below zero."""
    stmt = (
        update(InventoryStock)
        .where(
            InventoryStock.sku_id == sku_id,
            InventoryStock.warehouse_id == warehouse_id,
            InventoryStock.reserved_qty >= quantity,
        )
        .values(
            reserved_qty=InventoryStock.reserved_qty - quantity,
            version=InventoryStock.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    result = session.execute(stmt)
    return (result.rowcount or 0) > 0


def try_outbound_atomic(session: Session, sku_id: int, warehouse_id: int, quantity: int) -> bool:
    """Ship ``quantity`` out: physical stock and the reservation drop together.

    Both floors are part of the WHERE clause, so the row can never end up with
    negative on-hand or a reservation that outlived the stock it held.
    """
    stmt = (
        update(InventoryStock)
        .where(
            InventoryStock.sku_id == sku_id,
            InventoryStock.warehouse_id == warehouse_id,
            InventoryStock.on_hand_qty >= quantity,
            InventoryStock.reserved_qty >= quantity,
        )
        .values(
            on_hand_qty=InventoryStock.on_hand_qty - quantity,
            reserved_qty=InventoryStock.reserved_qty - quantity,
            version=InventoryStock.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    result = session.execute(stmt)
    return (result.rowcount or 0) > 0


def set_default_location(
    session: Session, stock: InventoryStock, location_id: int | None
) -> InventoryStock:
    """Remember the standing pick location for this SKU in this warehouse."""
    stock.default_location_id = location_id
    session.flush()
    return stock


def list_stocks(
    session: Session,
    *,
    sku_id: int | None = None,
    warehouse_id: int | None = None,
    keyword: str | None = None,
    low_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(InventoryStock)
    if sku_id:
        stmt = stmt.where(InventoryStock.sku_id == sku_id)
    if warehouse_id:
        stmt = stmt.where(InventoryStock.warehouse_id == warehouse_id)
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            InventoryStock.sku.has(
                or_(Sku.sku_code.like(pattern), Sku.barcode.like(pattern))
            )
        )
    if low_only:
        # 可售 <= 0  <=>  实际 - 已占用 - 安全 <= 0
        stmt = stmt.where(
            InventoryStock.on_hand_qty - InventoryStock.reserved_qty <= InventoryStock.safety_qty
        )
    stmt = stmt.order_by(InventoryStock.id.desc())
    return paginate(session, stmt, page, page_size)


# ------------------------------------------------------------------- ledger
def append_transaction(session: Session, **fields) -> InventoryTransaction:
    """Append one immutable ledger row."""
    tx = InventoryTransaction(**fields)
    session.add(tx)
    session.flush()
    return tx


def get_transaction_by_idempotency(session: Session, key: str) -> InventoryTransaction | None:
    return session.scalar(
        select(InventoryTransaction).where(InventoryTransaction.idempotency_key == key)
    )


def list_transactions(
    session: Session,
    *,
    sku_id: int | None = None,
    warehouse_id: int | None = None,
    type_: InventoryTransactionType | None = None,
    ref_type: str | None = None,
    ref_id: int | None = None,
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(InventoryTransaction).options(
        selectinload(InventoryTransaction.sku),
        selectinload(InventoryTransaction.warehouse),
        selectinload(InventoryTransaction.operator),
    )
    if sku_id:
        stmt = stmt.where(InventoryTransaction.sku_id == sku_id)
    if warehouse_id:
        stmt = stmt.where(InventoryTransaction.warehouse_id == warehouse_id)
    if type_:
        stmt = stmt.where(InventoryTransaction.type == type_)
    if ref_type:
        stmt = stmt.where(InventoryTransaction.ref_type == ref_type)
    if ref_id:
        stmt = stmt.where(InventoryTransaction.ref_id == ref_id)
    if start:
        stmt = stmt.where(InventoryTransaction.created_at >= start)
    if end:
        stmt = stmt.where(InventoryTransaction.created_at <= end)
    stmt = stmt.order_by(InventoryTransaction.id.desc())
    return paginate(session, stmt, page, page_size)


def sku_exists(session: Session, sku_id: int) -> bool:
    return session.get(Sku, sku_id) is not None


def warehouse_exists(session: Session, warehouse_id: int) -> bool:
    return session.get(Warehouse, warehouse_id) is not None


def operator_name(session: Session, operator_id: int | None) -> str:
    if not operator_id:
        return ""
    user = session.get(User, operator_id)
    return (user.full_name or user.username) if user else ""
