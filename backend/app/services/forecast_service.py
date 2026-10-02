"""Sales forecasting.

There is no model here, and deliberately so.  A moving average over the
inventory ledger is:

* explainable — 「近 30 天卖了 120 件」是个人能听懂的话；
* cheap — it is one grouped query over rows we already have;
* stable — a moving average does not hallucinate a spike and buy 10x stock.

Anything fancier would need history OmniStock does not have yet (M1 shipped
with no prior sales data at all), and a wrong forecast is expensive: it turns
into either a stockout or a pile of unsold goods.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain import replenish_formula
from app.models.base import utcnow


def window_bounds(days: int | None = None) -> tuple[dt.datetime, dt.datetime]:
    """``(start, end)`` of the look-back window, both naive UTC."""
    days = days or settings.FORECAST_WINDOW_DAYS
    end = utcnow()
    return end - dt.timedelta(days=max(days, 1)), end


def sold_in_window(
    session: Session, *, sku_id: int | None = None, days: int | None = None
) -> dict[int, int]:
    """Net units sold per SKU in the window (outbound minus returns)."""
    from app.repositories import report_repo

    start, end = window_bounds(days)
    sold = report_repo.net_sold_by_sku(session, start_at=start, end_at=end)
    if sku_id is None:
        return sold
    return {sku_id: sold.get(sku_id, 0)}


def average_stock(
    session: Session, *, sku_id: int | None = None, warehouse_id: int | None = None
) -> dict[int, float]:
    """Average on-hand per SKU across the window.

    Computed from the ledger's before/after snapshots rather than by sampling
    the current table: sampling once would only ever describe *now*, and would
    report an average of one sample.
    """
    from sqlalchemy import func, select

    from app.models.inventory import InventoryTransaction, InventoryTransactionType

    start, end = window_bounds()
    stmt = select(
        InventoryTransaction.sku_id,
        func.avg(
            (InventoryTransaction.on_hand_before + InventoryTransaction.on_hand_after) / 2.0
        ).label("avg_stock"),
    ).where(
        InventoryTransaction.created_at >= start,
        InventoryTransaction.created_at <= end,
        InventoryTransaction.type.in_(
            [
                InventoryTransactionType.PURCHASE_INBOUND,
                InventoryTransactionType.ORDER_OUTBOUND,
                InventoryTransactionType.MANUAL_ADJUST,
                InventoryTransactionType.TRANSFER_OUT,
                InventoryTransactionType.TRANSFER_IN,
                InventoryTransactionType.RETURN_INBOUND,
                InventoryTransactionType.STOCKTAKE_ADJUST,
            ]
        ),
    )
    if sku_id is not None:
        stmt = stmt.where(InventoryTransaction.sku_id == sku_id)
    if warehouse_id is not None:
        stmt = stmt.where(InventoryTransaction.warehouse_id == warehouse_id)
    stmt = stmt.group_by(InventoryTransaction.sku_id)
    return {int(row.sku_id): float(row.avg_stock or 0.0) for row in session.execute(stmt)}


def forecast_for_sku(
    session: Session,
    sku_id: int,
    *,
    days: int | None = None,
    lead_time_days: int | None = None,
) -> dict[str, float]:
    """Everything the replenishment formula needs, for one SKU."""
    days = days or settings.FORECAST_WINDOW_DAYS
    lead = settings.REPLENISH_LEAD_TIME_DAYS if lead_time_days is None else lead_time_days

    sold = sold_in_window(session, sku_id=sku_id, days=days).get(sku_id, 0)
    return {
        "window_days": float(days),
        "sold_qty": float(sold),
        "avg_daily_sales": replenish_formula.daily_average(sold, days),
        "forecast_qty": float(
            replenish_formula.forecast_quantity(sold, window_days=days, lead_time_days=lead)
        ),
    }
