"""经营报表。

每张报表的**口径**都写在字段注释和这里，因为报表最容易出的错不是算错，
而是两边对「及时率」「周转天数」的理解不一样。

两个统一口径：

* **净销量** = 出库 - 退货入库（见 :mod:`app.repositories.report_repo`）。
  直接把两类流水相加会让退货把销量变成负数。
* **周转天数** = 平均库存 / 日均销量；窗口内零销量时是 ``None`` 而不是 0 ——
  「卖不动」和「周转极快」是完全不同的两件事，不能都写成 0。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import REPORT_RANGE_INVALID, BusinessError
from app.domain import replenish_formula
from app.models.inventory import InventoryStock
from app.repositories import report_repo
from app.schemas.report import (
    ChannelSalesRow,
    DashboardSummary,
    LowStockRow,
    PurchaseAmountRow,
    ReturnRateRow,
    SlowMovingRow,
    SkuStockRow,
    StockoutRow,
    StocktakeVarianceRow,
    SupplierOnTimeRow,
    TurnoverRow,
)

DEFAULT_PERIOD_DAYS = settings.REPORT_DEFAULT_RANGE_DAYS


def resolve_range(
    start: dt.datetime | None, end: dt.datetime | None, days: int | None = None
) -> tuple[dt.datetime, dt.datetime]:
    """把「起止时间」或「最近 N 天」统一成 ``(start, end)``。"""
    if start and end:
        if start > end:
            raise BusinessError(REPORT_RANGE_INVALID, "开始时间不能晚于结束时间", http_status=400)
        return start, end
    span = days or DEFAULT_PERIOD_DAYS
    if span <= 0 or span > 3650:
        raise BusinessError(REPORT_RANGE_INVALID, "回看天数必须在 1 到 3650 之间", http_status=400)
    end = end or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    return end - dt.timedelta(days=span), end


# --------------------------------------------------------------- SKU 库存
def sku_stock(session: Session, *, warehouse_id: int | None = None) -> list[SkuStockRow]:
    stmt = select(InventoryStock)
    if warehouse_id is not None:
        stmt = stmt.where(InventoryStock.warehouse_id == warehouse_id)

    rows: list[SkuStockRow] = []
    for stock in session.scalars(stmt):
        sku = stock.sku
        rows.append(
            SkuStockRow(
                sku_id=stock.sku_id,
                sku_code=sku.sku_code if sku else "",
                sku_name=sku.display_name if sku else "",
                warehouse_id=stock.warehouse_id,
                warehouse_code=stock.warehouse.code if stock.warehouse else "",
                warehouse_name=stock.warehouse.name if stock.warehouse else "",
                on_hand_qty=stock.on_hand_qty,
                reserved_qty=stock.reserved_qty,
                in_transit_qty=stock.in_transit_qty,
                safety_qty=stock.safety_qty,
                defective_qty=stock.defective_qty,
                repair_qty=stock.repair_qty,
                available_qty=stock.available_qty,
                location_code=stock.default_location.code if stock.default_location else "",
                stock_value_cents=stock.on_hand_qty * (sku.purchase_price_cents if sku else 0),
            )
        )
    return rows


# --------------------------------------------------------------- 库存周转
def turnover(
    session: Session,
    *,
    start: dt.datetime,
    end: dt.datetime,
    warehouse_id: int | None = None,
) -> list[TurnoverRow]:
    """周转天数 = 平均库存 / 日均销量。"""
    sold = report_repo.net_sold_by_sku(session, start_at=start, end_at=end)
    avg = _average_stock(session, start, end, warehouse_id=warehouse_id)
    period_days = max((end - start).days, 1)

    rows: list[TurnoverRow] = []
    for sku_id, avg_stock in avg.items():
        qty = sold.get(sku_id, 0)
        daily = replenish_formula.daily_average(qty, period_days)
        rows.append(
            TurnoverRow(
                sku_id=sku_id,
                sku_code=_sku_code(session, sku_id),
                sku_name=_sku_name(session, sku_id),
                period_days=period_days,
                sold_qty=qty,
                avg_daily_sales=round(daily, 4),
                average_stock=round(avg_stock, 2),
                turnover_days=(round(avg_stock / daily, 2) if daily > 0 else None),
                on_hand_qty=_on_hand(session, sku_id, warehouse_id),
            )
        )
    rows.sort(key=lambda row: (row.turnover_days is None, row.turnover_days or 0))
    return rows


def _average_stock(
    session: Session, start: dt.datetime, end: dt.datetime, *, warehouse_id: int | None = None
) -> dict[int, float]:
    """窗口内的平均库存，用流水的前后值算，而不是只取当前值采样一次。"""
    from sqlalchemy import func

    from app.models.inventory import InventoryTransaction

    stmt = (
        select(
            InventoryTransaction.sku_id,
            func.avg(
                (InventoryTransaction.on_hand_before + InventoryTransaction.on_hand_after) / 2.0
            ),
        )
        .where(
            InventoryTransaction.created_at >= start,
            InventoryTransaction.created_at <= end,
        )
        .group_by(InventoryTransaction.sku_id)
    )
    if warehouse_id is not None:
        stmt = stmt.where(InventoryTransaction.warehouse_id == warehouse_id)
    return {int(sku_id): float(value or 0.0) for sku_id, value in session.execute(stmt)}


def _sku_code(session: Session, sku_id: int) -> str:
    from app.repositories import product_repo

    sku = product_repo.get_sku(session, sku_id)
    return sku.sku_code if sku else ""


def _sku_name(session: Session, sku_id: int) -> str:
    from app.repositories import product_repo

    sku = product_repo.get_sku(session, sku_id)
    return sku.display_name if sku else ""


def _on_hand(session: Session, sku_id: int, warehouse_id: int | None) -> int:
    stmt = select(InventoryStock).where(InventoryStock.sku_id == sku_id)
    if warehouse_id is not None:
        stmt = stmt.where(InventoryStock.warehouse_id == warehouse_id)
    return sum(row.on_hand_qty for row in session.scalars(stmt))


# ---------------------------------------------------------- 供应商及时率
def supplier_on_time(session: Session) -> list[SupplierOnTimeRow]:
    """及时率 = 按期批次 / 总批次；到货日 <= 预计到货日算按期。"""
    grouped: dict[int, dict] = {}
    for row in report_repo.supplier_receipts(session):
        bucket = grouped.setdefault(
            row["supplier_id"],
            {"name": row["supplier_name"], "total": 0, "on_time": 0, "delay_days": 0},
        )
        bucket["total"] += 1
        delay = (row["received_at"] - row["expected_at"]).days
        if delay <= 0:
            bucket["on_time"] += 1
        else:
            bucket["delay_days"] += delay

    rows = []
    for supplier_id, data in grouped.items():
        late = data["total"] - data["on_time"]
        rows.append(
            SupplierOnTimeRow(
                supplier_id=supplier_id,
                supplier_name=data["name"],
                total_batches=data["total"],
                on_time_batches=data["on_time"],
                late_batches=late,
                on_time_rate=round(data["on_time"] / data["total"], 4) if data["total"] else 0.0,
                avg_delay_days=round(data["delay_days"] / late, 2) if late else 0.0,
            )
        )
    rows.sort(key=lambda row: row.on_time_rate)
    return rows


# -------------------------------------------------------------- 渠道销量
def channel_sales(
    session: Session,
    *,
    start: dt.datetime,
    end: dt.datetime,
    granularity: str = "day",
    channel_id: int | None = None,
) -> list[ChannelSalesRow]:
    if granularity not in ("day", "week", "month"):
        raise BusinessError(REPORT_RANGE_INVALID, "granularity 只能是 day/week/month", http_status=400)
    rows = report_repo.channel_sales(
        session, start_at=start, end_at=end, granularity=granularity, channel_id=channel_id
    )
    return [ChannelSalesRow(**row) for row in rows]


# ---------------------------------------------------------------- 缺货次数
def stockout(
    session: Session, *, start: dt.datetime, end: dt.datetime
) -> list[StockoutRow]:
    rows = []
    for row in report_repo.stockout_by_sku(session, start_at=start, end_at=end):
        rows.append(StockoutRow(sku_name=_sku_name(session, row["sku_id"]), **row))
    return rows


# ------------------------------------------------------------------ 退货率
def return_rate(
    session: Session, *, start: dt.datetime, end: dt.datetime
) -> list[ReturnRateRow]:
    """退货率 = 退货数量 / 销售数量；分母为 0 时记 0。"""
    sold = report_repo.net_sold_by_sku(session, start_at=start, end_at=end)
    returned = _returned_by_sku(session, start, end)

    rows = []
    for sku_id, qty in sold.items():
        back = returned.get(sku_id, 0)
        rows.append(
            ReturnRateRow(
                sku_id=sku_id,
                sku_code=_sku_code(session, sku_id),
                sku_name=_sku_name(session, sku_id),
                sold_qty=max(qty, 0),
                returned_qty=back,
                return_rate=round(back / qty, 4) if qty > 0 else 0.0,
                return_order_count=_return_orders_for(session, sku_id, start, end),
            )
        )
    rows.sort(key=lambda row: row.return_rate, reverse=True)
    return rows


def _returned_by_sku(
    session: Session, start: dt.datetime, end: dt.datetime
) -> dict[int, int]:
    from sqlalchemy import func

    from app.models.return_order import ReturnOrder, ReturnOrderItem, ReturnStatus

    stmt = (
        select(ReturnOrderItem.sku_id, func.sum(ReturnOrderItem.quantity))
        .join(ReturnOrder, ReturnOrder.id == ReturnOrderItem.return_id)
        .where(
            ReturnOrder.status == ReturnStatus.INBOUND,
            ReturnOrder.inbound_at.is_not(None),
            ReturnOrder.inbound_at >= start,
            ReturnOrder.inbound_at <= end,
        )
        .group_by(ReturnOrderItem.sku_id)
    )
    return {int(sku_id): int(qty or 0) for sku_id, qty in session.execute(stmt)}


def _return_orders_for(
    session: Session, sku_id: int, start: dt.datetime, end: dt.datetime
) -> int:
    from sqlalchemy import func

    from app.models.return_order import ReturnOrder, ReturnOrderItem, ReturnStatus

    stmt = (
        select(func.count(func.distinct(ReturnOrderItem.return_id)))
        .join(ReturnOrder, ReturnOrder.id == ReturnOrderItem.return_id)
        .where(
            ReturnOrderItem.sku_id == sku_id,
            ReturnOrder.status == ReturnStatus.INBOUND,
            ReturnOrder.inbound_at >= start,
            ReturnOrder.inbound_at <= end,
        )
    )
    return int(session.scalar(stmt) or 0)


# ------------------------------------------------------------------ 滞销
def slow_moving(
    session: Session, *, start: dt.datetime, end: dt.datetime, idle_days: int | None = None
) -> list[SlowMovingRow]:
    """近 N 天零出货、但库里还有货的 SKU。"""
    span = idle_days or max((end - start).days, 1)
    sold = report_repo.net_sold_by_sku(session, start_at=start, end_at=end)
    last_out = report_repo.last_outbound_at_by_sku(session)

    rows: list[SlowMovingRow] = []
    stmt = select(InventoryStock).where(InventoryStock.on_hand_qty > 0)
    for stock in session.scalars(stmt):
        if sold.get(stock.sku_id, 0) > 0:
            continue
        sku = stock.sku
        last = last_out.get(stock.sku_id)
        days = (end - last).days if last else span
        rows.append(
            SlowMovingRow(
                sku_id=stock.sku_id,
                sku_code=sku.sku_code if sku else "",
                sku_name=sku.display_name if sku else "",
                warehouse_id=stock.warehouse_id,
                warehouse_code=stock.warehouse.code if stock.warehouse else "",
                on_hand_qty=stock.on_hand_qty,
                stock_value_cents=stock.on_hand_qty * (sku.purchase_price_cents if sku else 0),
                idle_days=min(days, 3650),
            )
        )
    rows.sort(key=lambda row: row.idle_days, reverse=True)
    return rows


# -------------------------------------------------------------- 采购金额
def purchase_amount(
    session: Session,
    *,
    start: dt.datetime,
    end: dt.datetime,
    granularity: str = "month",
    supplier_id: int | None = None,
) -> list[PurchaseAmountRow]:
    rows = report_repo.purchase_amount(
        session, start_at=start, end_at=end, granularity=granularity, supplier_id=supplier_id
    )
    return [PurchaseAmountRow(**row) for row in rows]


# -------------------------------------------------------------- 盘点差异
def stocktake_variance(session: Session) -> list[StocktakeVarianceRow]:
    """按仓库汇总已审核盘点的差异。只有审核过的才会动库存，所以只统计它们。"""
    return [StocktakeVarianceRow(**row) for row in report_repo.stocktake_variance(session)]


# ------------------------------------------------------------ 低库存清单
def low_stock(session: Session) -> list[LowStockRow]:
    """``可售 + 在途 < 安全库存`` 的清单，与预警扫描同一口径。"""
    rows: list[LowStockRow] = []
    for stock in session.scalars(select(InventoryStock)):
        if stock.safety_qty <= 0:
            continue
        if replenish_formula.is_low_stock(
            available_qty=stock.available_qty,
            in_transit_qty=stock.in_transit_qty,
            safety_qty=stock.safety_qty,
        ):
            sku = stock.sku
            rows.append(
                LowStockRow(
                    sku_id=stock.sku_id,
                    sku_code=sku.sku_code if sku else "",
                    sku_name=sku.display_name if sku else "",
                    warehouse_id=stock.warehouse_id,
                    warehouse_code=stock.warehouse.code if stock.warehouse else "",
                    warehouse_name=stock.warehouse.name if stock.warehouse else "",
                    available_qty=stock.available_qty,
                    in_transit_qty=stock.in_transit_qty,
                    safety_qty=stock.safety_qty,
                    gap_qty=replenish_formula.shortfall(
                        available_qty=stock.available_qty,
                        in_transit_qty=stock.in_transit_qty,
                        safety_qty=stock.safety_qty,
                    ),
                )
            )
    rows.sort(key=lambda row: row.gap_qty, reverse=True)
    return rows


# ------------------------------------------------------------ 看板汇总
def dashboard(session: Session, *, start: dt.datetime, end: dt.datetime) -> DashboardSummary:
    counts = report_repo.dashboard_counts(session)
    order_count, amount = period_sales(session, start=start, end=end)

    return DashboardSummary(
        **counts,
        period_days=max((end - start).days, 1),
        period_order_count=order_count,
        period_amount_cents=amount,
        low_stock_count=len(low_stock(session)),
    )


def period_sales(
    session: Session, *, start: dt.datetime, end: dt.datetime
) -> tuple[int, int]:
    """窗口内的订单量与金额，供看板顶部使用。"""
    from sqlalchemy import func

    from app.models.order import OrderStatus, SalesOrder

    stmt = (
        select(
            func.count(SalesOrder.id),
            func.coalesce(func.sum(SalesOrder.total_amount_cents), 0),
        )
        .where(
            SalesOrder.paid_at.is_not(None),
            SalesOrder.paid_at >= start,
            SalesOrder.paid_at <= end,
            SalesOrder.status != OrderStatus.CANCELLED,
            SalesOrder.deleted_at.is_(None),
        )
    )
    count, amount = session.execute(stmt).one()
    return int(count or 0), int(amount or 0)
