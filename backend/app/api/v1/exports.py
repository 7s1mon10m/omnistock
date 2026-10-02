"""CSV exports for every report.

The BOM is not cosmetic: Excel on Chinese Windows opens CSV as GBK by default,
so without it every header turns into mojibake and the file is unusable.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.api.v1.guards import ViewerGuard
from app.core.deps import DbSession
from app.services import export_service, inventory_service, report_service

router = APIRouter(prefix="/exports", tags=["exports"])

#: report name -> (filename, chinese headers, model field keys)
TABLES: dict[str, tuple[str, list[str], list[str]]] = {
    "sku-stock": (
        "SKU库存",
        [
            "SKU编码", "商品", "仓库", "实际库存", "已占用", "在途",
            "安全库存", "次品", "维修", "可售", "库位", "库存金额(元)",
        ],
        [
            "sku_code", "sku_name", "warehouse_name", "on_hand_qty", "reserved_qty",
            "in_transit_qty", "safety_qty", "defective_qty", "repair_qty",
            "available_qty", "location_code", "stock_value_cents",
        ],
    ),
    "turnover": (
        "库存周转",
        ["SKU编码", "商品", "回看天数", "销量", "日均销量", "平均库存", "周转天数", "当前库存"],
        [
            "sku_code", "sku_name", "period_days", "sold_qty", "avg_daily_sales",
            "average_stock", "turnover_days", "on_hand_qty",
        ],
    ),
    "supplier-ontime": (
        "供应商及时率",
        ["供应商", "总批次", "按期", "延误", "及时率", "平均延误天数"],
        [
            "supplier_name", "total_batches", "on_time_batches", "late_batches",
            "on_time_rate", "avg_delay_days",
        ],
    ),
    "channel-sales": (
        "渠道销量",
        ["时间", "渠道编码", "渠道", "订单数", "金额(元)"],
        ["bucket", "channel_code", "channel_name", "order_count", "total_amount_cents"],
    ),
    "stockout": (
        "缺货统计",
        ["SKU编码", "商品", "缺货次数", "缺口数量", "最近缺货时间"],
        ["sku_code", "sku_name", "stockout_count", "shortage_qty", "last_stockout_at"],
    ),
    "return-rate": (
        "退货率",
        ["SKU编码", "商品", "销量", "退货量", "退货率", "退货单数"],
        ["sku_code", "sku_name", "sold_qty", "returned_qty", "return_rate", "return_order_count"],
    ),
    "slow-moving": (
        "滞销商品",
        ["SKU编码", "商品", "仓库", "库存", "库存金额(元)", "闲置天数"],
        [
            "sku_code", "sku_name", "warehouse_code", "on_hand_qty",
            "stock_value_cents", "idle_days",
        ],
    ),
    "purchase-amount": (
        "采购金额",
        ["时间", "供应商", "采购单数", "金额(元)"],
        ["bucket", "supplier_name", "order_count", "total_amount_cents"],
    ),
    "stocktake-variance": (
        "盘点差异",
        ["仓库编码", "仓库", "盘点行数", "差异行数", "盘盈", "盘亏", "净差异"],
        [
            "warehouse_code", "warehouse_name", "total_lines", "variance_lines",
            "gain_qty", "loss_qty", "net_qty",
        ],
    ),
    "low-stock": (
        "低库存清单",
        ["SKU编码", "商品", "仓库", "可售", "在途", "安全库存", "缺口"],
        [
            "sku_code", "sku_name", "warehouse_name", "available_qty",
            "in_transit_qty", "safety_qty", "gap_qty",
        ],
    ),
}


def _range(start, end, days) -> tuple[dt.datetime, dt.datetime]:
    return report_service.resolve_range(
        inventory_service.parse_dt(start), inventory_service.parse_dt(end), days
    )


@router.get("/{report}.csv", summary="导出报表 CSV（Excel 可直接打开）")
def export_report(
    report: str,
    session: DbSession,
    _: ViewerGuard,
    start: str | None = None,
    end: str | None = None,
    days: int | None = Query(None, ge=1, le=3650),
    granularity: str = "day",
    warehouse_id: int | None = None,
) -> StreamingResponse:
    if report not in TABLES:
        from app.core.errors import REPORT_RANGE_INVALID, BusinessError

        raise BusinessError(REPORT_RANGE_INVALID, f"没有 {report} 这张报表", http_status=404)

    filename, headers, keys = TABLES[report]
    start_at, end_at = _range(start, end, days)

    if report == "sku-stock":
        rows = [row.model_dump() for row in report_service.sku_stock(session, warehouse_id=warehouse_id)]
    elif report == "turnover":
        rows = [
            row.model_dump()
            for row in report_service.turnover(
                session, start=start_at, end=end_at, warehouse_id=warehouse_id
            )
        ]
    elif report == "supplier-ontime":
        rows = [row.model_dump() for row in report_service.supplier_on_time(session)]
    elif report == "channel-sales":
        rows = [
            row.model_dump()
            for row in report_service.channel_sales(
                session, start=start_at, end=end_at, granularity=granularity
            )
        ]
    elif report == "stockout":
        rows = [row.model_dump() for row in report_service.stockout(session, start=start_at, end=end_at)]
    elif report == "return-rate":
        rows = [row.model_dump() for row in report_service.return_rate(session, start=start_at, end=end_at)]
    elif report == "slow-moving":
        rows = [row.model_dump() for row in report_service.slow_moving(session, start=start_at, end=end_at)]
    elif report == "purchase-amount":
        rows = [
            row.model_dump()
            for row in report_service.purchase_amount(
                session, start=start_at, end=end_at, granularity=granularity
            )
        ]
    elif report == "stocktake-variance":
        rows = [row.model_dump() for row in report_service.stocktake_variance(session)]
    else:
        rows = [row.model_dump() for row in report_service.low_stock(session)]

    # 金额从「分」转成「元」，导出的表格是要给人读的
    for row in rows:
        for key, value in row.items():
            if key.endswith("_cents") and isinstance(value, int):
                row[key] = f"{value / 100:.2f}"

    return export_service.csv_response(
        f"{filename}_{start_at:%Y%m%d}_{end_at:%Y%m%d}", headers, [[r.get(k, "") for k in keys] for r in rows]
    )
