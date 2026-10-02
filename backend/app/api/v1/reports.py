"""Management reports.

Every endpoint takes an explicit date range.  Reports that silently default to
"all time" look fine in month one and then get slower and less meaningful every
month after.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query

from app.api.v1.guards import AdminGuard, ViewerGuard
from app.core.deps import DbSession
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
from app.services import inventory_service, report_service

router = APIRouter(prefix="/reports", tags=["reports"])


def _range(
    start: str | None, end: str | None, days: int | None
) -> tuple[dt.datetime, dt.datetime]:
    return report_service.resolve_range(
        inventory_service.parse_dt(start), inventory_service.parse_dt(end), days
    )


@router.get("/dashboard", response_model=DashboardSummary, summary="经营看板汇总")
def dashboard(
    session: DbSession,
    _: ViewerGuard,
    start: str | None = None,
    end: str | None = None,
    days: int | None = Query(None, ge=1, le=3650),
) -> DashboardSummary:
    start_at, end_at = _range(start, end, days)
    return report_service.dashboard(session, start=start_at, end=end_at)


@router.get("/sku-stock", response_model=list[SkuStockRow], summary="SKU 库存报表")
def sku_stock(
    session: DbSession, _: ViewerGuard, warehouse_id: int | None = None
) -> list[SkuStockRow]:
    return report_service.sku_stock(session, warehouse_id=warehouse_id)


@router.get("/turnover", response_model=list[TurnoverRow], summary="库存周转天数")
def turnover(
    session: DbSession,
    _: ViewerGuard,
    start: str | None = None,
    end: str | None = None,
    days: int | None = Query(None, ge=1, le=3650),
    warehouse_id: int | None = None,
) -> list[TurnoverRow]:
    start_at, end_at = _range(start, end, days)
    return report_service.turnover(
        session, start=start_at, end=end_at, warehouse_id=warehouse_id
    )


@router.get("/supplier-ontime", response_model=list[SupplierOnTimeRow], summary="供应商交付及时率")
def supplier_on_time(session: DbSession, _: ViewerGuard) -> list[SupplierOnTimeRow]:
    return report_service.supplier_on_time(session)


@router.get("/channel-sales", response_model=list[ChannelSalesRow], summary="渠道销量对比")
def channel_sales(
    session: DbSession,
    _: ViewerGuard,
    start: str | None = None,
    end: str | None = None,
    days: int | None = Query(None, ge=1, le=3650),
    granularity: str = "day",
    channel_id: int | None = None,
) -> list[ChannelSalesRow]:
    start_at, end_at = _range(start, end, days)
    return report_service.channel_sales(
        session,
        start=start_at,
        end=end_at,
        granularity=granularity,
        channel_id=channel_id,
    )


@router.get("/stockout", response_model=list[StockoutRow], summary="缺货次数")
def stockout(
    session: DbSession,
    _: ViewerGuard,
    start: str | None = None,
    end: str | None = None,
    days: int | None = Query(None, ge=1, le=3650),
) -> list[StockoutRow]:
    start_at, end_at = _range(start, end, days)
    return report_service.stockout(session, start=start_at, end=end_at)


@router.get("/return-rate", response_model=list[ReturnRateRow], summary="退货率")
def return_rate(
    session: DbSession,
    _: ViewerGuard,
    start: str | None = None,
    end: str | None = None,
    days: int | None = Query(None, ge=1, le=3650),
) -> list[ReturnRateRow]:
    start_at, end_at = _range(start, end, days)
    return report_service.return_rate(session, start=start_at, end=end_at)


@router.get("/slow-moving", response_model=list[SlowMovingRow], summary="滞销商品")
def slow_moving(
    session: DbSession,
    _: ViewerGuard,
    start: str | None = None,
    end: str | None = None,
    days: int | None = Query(None, ge=1, le=3650),
) -> list[SlowMovingRow]:
    start_at, end_at = _range(start, end, days)
    return report_service.slow_moving(session, start=start_at, end=end_at)


@router.get("/purchase-amount", response_model=list[PurchaseAmountRow], summary="采购金额")
def purchase_amount(
    session: DbSession,
    _: ViewerGuard,
    start: str | None = None,
    end: str | None = None,
    days: int | None = Query(None, ge=1, le=3650),
    granularity: str = "month",
    supplier_id: int | None = None,
) -> list[PurchaseAmountRow]:
    start_at, end_at = _range(start, end, days)
    return report_service.purchase_amount(
        session,
        start=start_at,
        end=end_at,
        granularity=granularity,
        supplier_id=supplier_id,
    )


@router.get("/stocktake-variance", response_model=list[StocktakeVarianceRow], summary="盘点差异")
def stocktake_variance(session: DbSession, _: ViewerGuard) -> list[StocktakeVarianceRow]:
    return report_service.stocktake_variance(session)


@router.get("/low-stock", response_model=list[LowStockRow], summary="即将低于安全库存")
def low_stock(session: DbSession, _: ViewerGuard) -> list[LowStockRow]:
    return report_service.low_stock(session)
