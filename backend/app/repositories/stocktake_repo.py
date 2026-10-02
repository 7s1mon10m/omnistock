"""Stocktake data access."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.stocktake import Stocktake, StocktakeItem, StocktakeStatus
from app.utils.pagination import PageResult, paginate


def get(session: Session, stocktake_id: int) -> Stocktake | None:
    return session.get(Stocktake, stocktake_id)


def get_by_no(session: Session, stocktake_no: str) -> Stocktake | None:
    stmt = select(Stocktake).where(Stocktake.stocktake_no == stocktake_no)
    return session.scalar(stmt)


def get_item(session: Session, item_id: int) -> StocktakeItem | None:
    return session.get(StocktakeItem, item_id)


def list_stocktakes(
    session: Session,
    *,
    status: StocktakeStatus | None = None,
    warehouse_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(Stocktake)
    if status:
        stmt = stmt.where(Stocktake.status == status)
    if warehouse_id:
        stmt = stmt.where(Stocktake.warehouse_id == warehouse_id)
    stmt = stmt.order_by(Stocktake.id.desc())
    return paginate(session, stmt, page, page_size)


def create(session: Session, **fields) -> Stocktake:
    stocktake = Stocktake(**fields)
    session.add(stocktake)
    session.flush()
    return stocktake


def create_item(session: Session, **fields) -> StocktakeItem:
    item = StocktakeItem(**fields)
    session.add(item)
    session.flush()
    return item


def book_qty_map(session: Session, warehouse_id: int) -> dict[int, int]:
    """该仓所有 SKU 的账面库存快照。只取实际库存口径。"""
    from sqlalchemy import func

    from app.models.inventory import InventoryStock

    stmt = (
        select(InventoryStock.sku_id, func.sum(InventoryStock.on_hand_qty).label("qty"))
        .where(
            InventoryStock.warehouse_id == warehouse_id,
            InventoryStock.on_hand_qty > 0,
        )
        .group_by(InventoryStock.sku_id)
    )
    return {int(sku_id): int(qty or 0) for sku_id, qty in session.execute(stmt)}
