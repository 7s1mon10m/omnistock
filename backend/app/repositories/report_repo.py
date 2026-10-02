"""Report aggregations.

聚合全部走 SQL，不把表拉进 Python 再算 —— 报表一旦有了几十万个 SKU 行，
Python 侧循环就是瓶颈。这里每条语句都只返回聚合结果。

时间粒度用 SQLite 与 PostgreSQL **都支持**的表达式：``strftime`` 与
``to_char`` 在各自方言里注册成同一个 ``_period``，业务代码里不必判断
数据库类型。

**净销量**的口径值得单独说一句：出库流水记负数、退货入库记正数，所以
「净销量 = -(出库 + 退货入库)」。直接把两类流水相加是错的 —— 退 3 件会让
销量变成负的而不是减少 3。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import engine


def _period(column, granularity: str):
    """A date column truncated to day / week / month, portable across dialects."""
    dialect = engine.dialect.name
    if granularity == "week":
        # year-week, e.g. 2026-40
        if dialect == "postgresql":
            return func.to_char(column, "IYYY-IW")
        return func.strftime("%Y-%W", column)
    if granularity == "month":
        if dialect == "postgresql":
            return func.to_char(column, "YYYY-MM")
        return func.strftime("%Y-%m", column)
    if dialect == "postgresql":
        return func.to_char(column, "YYYY-MM-DD")
    return func.strftime("%Y-%m-%d", column)


# ------------------------------------------------------------- 渠道销量对比
def channel_sales(
    session: Session,
    *,
    start_at: dt.datetime,
    end_at: dt.datetime,
    granularity: str = "day",
    channel_id: int | None = None,
) -> list[dict]:
    """按渠道 × 时间桶聚合订单量与金额。取消的单不计入。"""
    from sqlalchemy import func as sa_func

    from app.models.channel import Channel
    from app.models.order import OrderStatus, SalesOrder, SalesOrderItem

    bucket = _period(SalesOrder.paid_at, granularity).label("bucket")
    # 件数来自订单行，用子查询按订单先汇总，避免 join 把金额重复计数。
    qty_per_order = (
        select(
            SalesOrderItem.order_id.label("order_id"),
            sa_func.sum(SalesOrderItem.quantity).label("qty"),
        )
        .group_by(SalesOrderItem.order_id)
        .subquery()
    )
    stmt = (
        select(
            bucket,
            SalesOrder.channel_id,
            Channel.code,
            Channel.name,
            func.count(func.distinct(SalesOrder.id)).label("order_count"),
            func.sum(SalesOrder.total_amount_cents).label("amount"),
            func.coalesce(func.sum(qty_per_order.c.qty), 0).label("quantity"),
        )
        .join(Channel, Channel.id == SalesOrder.channel_id)
        .outerjoin(qty_per_order, qty_per_order.c.order_id == SalesOrder.id)
        .where(
            SalesOrder.paid_at.is_not(None),
            SalesOrder.paid_at >= start_at,
            SalesOrder.paid_at <= end_at,
            SalesOrder.status != OrderStatus.CANCELLED,
            SalesOrder.deleted_at.is_(None),
        )
        .group_by(bucket, SalesOrder.channel_id, Channel.code, Channel.name)
        .order_by(bucket, SalesOrder.channel_id)
    )
    if channel_id is not None:
        stmt = stmt.where(SalesOrder.channel_id == channel_id)
    return [
        {
            "bucket": row.bucket or "",
            "channel_id": row.channel_id,
            "channel_code": row.code or "",
            "channel_name": row.name or "",
            "order_count": int(row.order_count or 0),
            "item_quantity": int(row.quantity or 0),
            "total_amount_cents": int(row.amount or 0),
        }
        for row in session.execute(stmt)
    ]


# --------------------------------------------------------------- 缺货次数
def stockout_by_sku(
    session: Session, *, start_at: dt.datetime, end_at: dt.datetime
) -> list[dict]:
    """按 SKU 统计进入异常队列的次数。"""
    from app.models.order import ExceptionType, OrderException
    from app.models.product import Sku

    stmt = (
        select(
            OrderException.sku_id,
            Sku.sku_code,
            func.count(OrderException.id).label("cnt"),
            # required - available 就是当时的缺口；不满足时该行为 0。
            func.sum(
                case(
                    (OrderException.required_qty > OrderException.available_qty,
                     OrderException.required_qty - OrderException.available_qty),
                    else_=0,
                )
            ).label("shortage"),
            func.max(OrderException.created_at).label("last_at"),
        )
        .join(Sku, Sku.id == OrderException.sku_id)
        .where(
            OrderException.type == ExceptionType.STOCK_SHORTAGE,
            OrderException.created_at >= start_at,
            OrderException.created_at <= end_at,
        )
        .group_by(OrderException.sku_id, Sku.sku_code)
        .order_by(func.count(OrderException.id).desc())
    )
    return [
        {
            "sku_id": row.sku_id,
            "sku_code": row.sku_code or "",
            "stockout_count": int(row.cnt or 0),
            "shortage_qty": int(row.shortage or 0),
            "last_stockout_at": row.last_at,
        }
        for row in session.execute(stmt)
    ]


# --------------------------------------------------------------- 采购金额
def purchase_amount(
    session: Session,
    *,
    start_at: dt.datetime,
    end_at: dt.datetime,
    granularity: str = "month",
    supplier_id: int | None = None,
) -> list[dict]:
    """按供应商 × 时间桶聚合采购金额（以**下单日**为口径）。"""
    from app.models.purchase import PurchaseOrder, PurchaseOrderStatus
    from app.models.supplier import Supplier

    bucket = _period(PurchaseOrder.ordered_at, granularity).label("bucket")
    stmt = (
        select(
            bucket,
            PurchaseOrder.supplier_id,
            Supplier.name,
            func.count(PurchaseOrder.id).label("orders"),
            func.sum(PurchaseOrder.total_amount_cents).label("amount"),
        )
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .where(
            PurchaseOrder.ordered_at.is_not(None),
            PurchaseOrder.ordered_at >= start_at,
            PurchaseOrder.ordered_at <= end_at,
            PurchaseOrder.status != PurchaseOrderStatus.CANCELLED,
            PurchaseOrder.deleted_at.is_(None),
        )
        .group_by(bucket, PurchaseOrder.supplier_id, Supplier.name)
        .order_by(bucket, PurchaseOrder.supplier_id)
    )
    if supplier_id is not None:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    return [
        {
            "bucket": row.bucket or "",
            "supplier_id": row.supplier_id,
            "supplier_name": row.name or "",
            "order_count": int(row.orders or 0),
            "total_amount_cents": int(row.amount or 0),
        }
        for row in session.execute(stmt)
    ]


# ------------------------------------------------------- 供应商交付及时率
def supplier_receipts(session: Session) -> list[dict]:
    """每一批到货的「预计 vs 实际」，供服务层算及时率。

    口径：以**首张收货单**的到货时间对比采购单的预计到货日。没有预计到货日的
    采购单不计入分母 —— 否则每一批都会算成「按时」，把及时率刷成 100%。
    """
    from app.models.purchase import PurchaseOrder, PurchaseReceipt, ReceiptStatus, Supplier

    stmt = (
        select(
            PurchaseOrder.supplier_id,
            Supplier.name,
            PurchaseOrder.id.label("order_id"),
            PurchaseOrder.expected_at,
            func.min(PurchaseReceipt.received_at).label("first_received_at"),
        )
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .join(PurchaseReceipt, PurchaseReceipt.order_id == PurchaseOrder.id)
        .where(
            PurchaseReceipt.status == ReceiptStatus.POSTED,
            PurchaseReceipt.received_at.is_not(None),
            PurchaseOrder.expected_at.is_not(None),
            PurchaseOrder.deleted_at.is_(None),
        )
        .group_by(
            PurchaseOrder.supplier_id,
            Supplier.name,
            PurchaseOrder.id,
            PurchaseOrder.expected_at,
        )
    )
    return [
        {
            "supplier_id": row.supplier_id,
            "supplier_name": row.name or "",
            "order_id": row.order_id,
            "expected_at": row.expected_at,
            "received_at": row.first_received_at,
        }
        for row in session.execute(stmt)
    ]


# ----------------------------------------------------------------- 销售明细
def net_sold_by_sku(
    session: Session, *, start_at: dt.datetime, end_at: dt.datetime
) -> dict[int, int]:
    """区间内每个 SKU 的**净销量** = 出库 - 退货入库。"""
    from app.models.inventory import InventoryTransaction, InventoryTransactionType

    stmt = (
        select(
            InventoryTransaction.sku_id,
            func.sum(
                case(
                    (
                        InventoryTransaction.type.in_(
                            [
                                InventoryTransactionType.ORDER_OUTBOUND,
                                InventoryTransactionType.RETURN_INBOUND,
                            ]
                        ),
                        -InventoryTransaction.qty_delta,
                    ),
                    else_=0,
                )
            ).label("net_sold"),
        )
        .where(
            InventoryTransaction.created_at >= start_at,
            InventoryTransaction.created_at <= end_at,
            InventoryTransaction.type.in_(
                [
                    InventoryTransactionType.ORDER_OUTBOUND,
                    InventoryTransactionType.RETURN_INBOUND,
                ]
            ),
        )
        .group_by(InventoryTransaction.sku_id)
    )
    return {int(sku_id): int(net or 0) for sku_id, net in session.execute(stmt)}


def last_outbound_at_by_sku(session: Session) -> dict[int, dt.datetime]:
    from app.models.inventory import InventoryTransaction, InventoryTransactionType

    stmt = (
        select(InventoryTransaction.sku_id, func.max(InventoryTransaction.created_at))
        .where(InventoryTransaction.type == InventoryTransactionType.ORDER_OUTBOUND)
        .group_by(InventoryTransaction.sku_id)
    )
    return {int(sku_id): last for sku_id, last in session.execute(stmt)}


# --------------------------------------------------------------- 采购单明细
def purchase_amount_detail(
    session: Session, *, start_at: dt.datetime, end_at: dt.datetime
) -> list[dict]:
    """逐单金额，用于按供应商汇总（不按时间桶）。"""
    from app.models.purchase import PurchaseOrder, PurchaseOrderStatus
    from app.models.supplier import Supplier

    stmt = (
        select(
            PurchaseOrder.supplier_id,
            Supplier.name,
            PurchaseOrder.id,
            PurchaseOrder.total_amount_cents,
            PurchaseOrder.status,
        )
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .where(
            PurchaseOrder.ordered_at.is_not(None),
            PurchaseOrder.ordered_at >= start_at,
            PurchaseOrder.ordered_at <= end_at,
            PurchaseOrder.status != PurchaseOrderStatus.CANCELLED,
            PurchaseOrder.deleted_at.is_(None),
        )
    )
    return [
        {
            "supplier_id": row.supplier_id,
            "supplier_name": row.name or "",
            "order_id": row.id,
            "total_amount_cents": int(row.total_amount_cents or 0),
            "status": row.status,
        }
        for row in session.execute(stmt)
    ]


# --------------------------------------------------------------- 盘点差异
def stocktake_variance(session: Session) -> list[dict]:
    """按仓库汇总已审核盘点的差异。未盘的行视作无差异（coalesce 到 book）。"""
    from app.models.stocktake import Stocktake, StocktakeItem, StocktakeStatus
    from app.models.warehouse import Warehouse

    variance = func.coalesce(StocktakeItem.counted_qty, StocktakeItem.book_qty) - (
        StocktakeItem.book_qty
    )
    stmt = (
        select(
            Stocktake.warehouse_id,
            Warehouse.code,
            Warehouse.name,
            func.count(StocktakeItem.id).label("lines"),
            func.sum(case((variance != 0, 1), else_=0)).label("variance_lines"),
            func.sum(case((variance > 0, variance), else_=0)).label("gain"),
            func.sum(case((variance < 0, -variance), else_=0)).label("loss"),
            func.sum(variance).label("net"),
        )
        .join(Warehouse, Warehouse.id == Stocktake.warehouse_id)
        .join(StocktakeItem, StocktakeItem.stocktake_id == Stocktake.id)
        .where(Stocktake.status == StocktakeStatus.APPROVED)
        .group_by(Stocktake.warehouse_id, Warehouse.code, Warehouse.name)
        .order_by(Stocktake.warehouse_id)
    )
    return [
        {
            "warehouse_id": row.warehouse_id,
            "warehouse_code": row.code or "",
            "warehouse_name": row.name or "",
            "total_lines": int(row.lines or 0),
            "variance_lines": int(row.variance_lines or 0),
            "gain_qty": int(row.gain or 0),
            "loss_qty": int(row.loss or 0),
            "net_qty": int(row.net or 0),
        }
        for row in session.execute(stmt)
    ]


# --------------------------------------------------------------- 看板汇总数字
def dashboard_counts(session: Session) -> dict[str, int]:
    """看板顶部几个数字，一次查询拿完。"""
    from app.models.alert import Alert as AlertModel
    from app.models.alert import AlertStatus
    from app.models.inventory import InventoryStock
    from app.models.order import ExceptionStatus, OrderException, OrderStatus, SalesOrder
    from app.models.product import Sku
    from app.models.stocktake import Stocktake, StocktakeStatus
    from app.models.supplier import Supplier
    from app.models.warehouse import Warehouse

    def scalar(stmt) -> int:
        return int(session.scalar(stmt) or 0)

    # 库存金额按采购价估算：这是「压了多少钱在库里」，不是能卖多少钱。
    total_stock_value = session.execute(
        select(
            func.coalesce(
                func.sum(InventoryStock.on_hand_qty * Sku.purchase_price_cents), 0
            )
        ).join(Sku, Sku.id == InventoryStock.sku_id)
    ).scalar_one()

    return {
        "sku_count": scalar(
            select(func.count()).select_from(Sku).where(Sku.deleted_at.is_(None))
        ),
        "total_stock_value_cents": int(total_stock_value or 0),
        "warehouse_count": scalar(
            select(func.count()).select_from(Warehouse).where(Warehouse.deleted_at.is_(None))
        ),
        "supplier_count": scalar(
            select(func.count()).select_from(Supplier).where(Supplier.deleted_at.is_(None))
        ),
        "total_on_hand": scalar(
            select(func.coalesce(func.sum(InventoryStock.on_hand_qty), 0)).select_from(
                InventoryStock
            )
        ),
        # 看板上的「可用」含安全库存，与 API 的 available 口径保持一致。
        "total_available": scalar(
            select(
                func.coalesce(
                    func.sum(
                        InventoryStock.on_hand_qty
                        - InventoryStock.reserved_qty
                        - InventoryStock.safety_qty
                    ),
                    0,
                )
            ).select_from(InventoryStock)
        ),
        "open_orders": scalar(
            select(func.count())
            .select_from(SalesOrder)
            .where(
                SalesOrder.status.in_(
                    [
                        OrderStatus.PENDING_PAYMENT,
                        OrderStatus.PENDING_FULFILLMENT,
                        OrderStatus.RESERVED,
                        OrderStatus.PICKING,
                    ]
                ),
                SalesOrder.deleted_at.is_(None),
            )
        ),
        "open_alerts": scalar(
            select(func.count())
            .select_from(AlertModel)
            .where(AlertModel.status == AlertStatus.OPEN)
        ),
        "open_exceptions": scalar(
            select(func.count())
            .select_from(OrderException)
            .where(OrderException.status == ExceptionStatus.OPEN)
        ),
        "pending_stocktakes": scalar(
            select(func.count())
            .select_from(Stocktake)
            .where(Stocktake.status.in_([StocktakeStatus.DRAFT, StocktakeStatus.SUBMITTED]))
        ),
    }
