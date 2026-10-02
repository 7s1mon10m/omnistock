"""Replenishment arithmetic.

Kept as pure functions with no database access so the formula can be reasoned
about (and unit tested) on its own.  The single rule everything else follows::

    suggested = forecast + safety - available - in_transit

两个容易搞错的地方，这个模块负责把它们钉死：

1. **在途要扣。** 已下单还在路上的货算进缺口，就会重复采购一次。
2. **结果不能为负。** 库存已经超过预测需求时，正确答案是「不用买」，
   而不是「买 -30 件」。
"""

from __future__ import annotations

import math


def daily_average(sold_qty: int, window_days: int) -> float:
    """Average units sold per day over the window.

    A zero-length window would divide by zero; treat it as "no sales observed"
    so callers get 0.0 rather than an exception.
    """
    if window_days <= 0:
        return 0.0
    return sold_qty / window_days


def forecast_quantity(
    sold_qty: int, *, window_days: int, lead_time_days: int
) -> int:
    """How much is expected to sell before the next delivery lands.

    Rounded **up**: buying half a box of shampoo is not a thing, and rounding
    down systematically under-orders by one unit per cycle.
    """
    return math.ceil(daily_average(sold_qty, window_days) * max(lead_time_days, 0))


def suggested_quantity(
    *,
    forecast_qty: int,
    safety_qty: int,
    available_qty: int,
    in_transit_qty: int,
) -> int:
    """建议采购量 = 预测销量 + 安全库存 - 可售 - 在途，负数归零。"""
    gap = forecast_qty + max(safety_qty, 0) - available_qty - in_transit_qty
    return gap if gap > 0 else 0


def is_low_stock(
    *, available_qty: int, in_transit_qty: int, safety_qty: int
) -> bool:
    """The alert rule: 可售 + 在途 < 安全库存。"""
    return (available_qty + in_transit_qty) < safety_qty


def shortfall(*, available_qty: int, in_transit_qty: int, safety_qty: int) -> int:
    """How far below safety stock we are; 0 when healthy."""
    gap = safety_qty - (available_qty + in_transit_qty)
    return gap if gap > 0 else 0
