"""Return order data access."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.return_order import (
    ReturnOrder,
    ReturnOrderItem,
    ReturnStatus,
)
from app.utils.pagination import PageResult, paginate


def get(session: Session, return_id: int) -> ReturnOrder | None:
    return session.get(ReturnOrder, return_id)


def get_by_no(session: Session, return_no: str) -> ReturnOrder | None:
    stmt = select(ReturnOrder).where(ReturnOrder.return_no == return_no)
    return session.scalar(stmt)


def get_item(session: Session, item_id: int) -> ReturnOrderItem | None:
    return session.get(ReturnOrderItem, item_id)


def list_returns(
    session: Session,
    *,
    status: ReturnStatus | None = None,
    warehouse_id: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(ReturnOrder)
    if status:
        stmt = stmt.where(ReturnOrder.status == status)
    if warehouse_id:
        stmt = stmt.where(ReturnOrder.warehouse_id == warehouse_id)
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            ReturnOrder.return_no.like(pattern)
            | ReturnOrder.channel_order_no.like(pattern)
            | ReturnOrder.buyer_nick.like(pattern)
        )
    stmt = stmt.order_by(ReturnOrder.id.desc())
    return paginate(session, stmt, page, page_size)


def count_shipped_by_sku(session: Session, order_id: int) -> dict[int, int]:
    """原订单里每个 SKU 的**已出库**数量。

    可退量的基准是「已卖出的」，不是「已下单的」——没发货的还能直接取消，
    拿来退货是重复动作。组合商品的销量按 M2 记的占用流水反算，与拣货清单
    同一口径。
    """
    from sqlalchemy import func

    from app.models.inventory import InventoryTransaction, InventoryTransactionType
    from app.models.order import SalesOrder, SalesOrderItem

    # 组合商品的子件销量：从库存流水的 ref_type=sales_order 汇总。
    stmt = (
        select(
            InventoryTransaction.sku_id,
            func.sum(InventoryTransaction.qty_delta).label("qty"),
        )
        .join(SalesOrder, SalesOrder.id == InventoryTransaction.ref_id)
        .where(
            SalesOrder.id == order_id,
            InventoryTransaction.ref_type == "sales_order",
            InventoryTransaction.type
            == InventoryTransactionType.ORDER_OUTBOUND,
        )
        .group_by(InventoryTransaction.sku_id)
    )
    outbound: dict[int, int] = {
        sku_id: -int(qty or 0) for sku_id, qty in session.execute(stmt)
    }

    # 普通商品的销量：直接看订单行。
    rows = (
        select(SalesOrderItem.sku_id, func.sum(SalesOrderItem.quantity).label("qty"))
        .where(SalesOrderItem.order_id == order_id)
        .group_by(SalesOrderItem.sku_id)
    )
    for sku_id, qty in session.execute(rows):
        sku_id = int(sku_id)
        if sku_id in outbound:
            # 套装子件以出库为准，普通行不要重复计入
            continue
        outbound[sku_id] = int(qty or 0)
    return outbound


def sum_returned_by_sku(session: Session, order_id: int, *, exclude_return_id: int | None = None) -> dict[int, int]:
    """原订单下所有**已入库**退货单里每个 SKU 的已退数量。

    只有 inbound 的退货单算数：还在待质检的退货单随时可能撤单，提前占用额度
    会让「已售 - 已退」算不准。
    """
    from sqlalchemy import func

    stmt = (
        select(
            ReturnOrderItem.sku_id,
            func.sum(ReturnOrderItem.quantity).label("qty"),
        )
        .join(ReturnOrder, ReturnOrder.id == ReturnOrderItem.return_id)
        .where(
            ReturnOrder.order_id == order_id,
            ReturnOrder.status == ReturnStatus.INBOUND,
        )
        .group_by(ReturnOrderItem.sku_id)
    )
    if exclude_return_id is not None:
        stmt = stmt.where(ReturnOrder.id != exclude_return_id)
    return {int(sku_id): int(qty or 0) for sku_id, qty in session.execute(stmt)}


def create(session: Session, **fields) -> ReturnOrder:
    return_order = ReturnOrder(**fields)
    session.add(return_order)
    session.flush()
    return return_order


def create_item(session: Session, **fields) -> ReturnOrderItem:
    item = ReturnOrderItem(**fields)
    session.add(item)
    session.flush()
    return item
