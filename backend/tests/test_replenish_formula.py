"""补货公式的纯函数测试。

这些用例不碰数据库 —— 公式本身就该能独立推理。真正重要的两条：

* **在途要扣** —— 已经下单在路上的货再算一次缺口，就是重复采购；
* **结果不为负** —— 库存够了就该回答「不用买」，而不是「买 -30 件」。
"""

from __future__ import annotations

import pytest

from app.domain import replenish_formula as f


class TestDailyAverage:
    def test_the_obvious_case(self):
        assert f.daily_average(300, 30) == 10.0

    def test_a_short_window_still_divides_by_the_window(self):
        # 7 天卖了 70 件 = 每天 10 件，不是每天 70 件
        assert f.daily_average(70, 7) == 10.0

    def test_no_sales_is_zero_not_an_error(self):
        assert f.daily_average(0, 30) == 0.0

    def test_a_zero_length_window_does_not_divide_by_zero(self):
        assert f.daily_average(100, 0) == 0.0


class TestForecastQuantity:
    def test_forecast_is_the_lead_time_worth_of_sales(self):
        # 每天 10 件 × 7 天交期 = 70
        assert f.forecast_quantity(300, window_days=30, lead_time_days=7) == 70

    def test_rounds_up_because_you_cannot_buy_half_a_unit(self):
        # 每天 1.4 件 × 7 天 = 9.8 → 10
        assert f.forecast_quantity(42, window_days=30, lead_time_days=7) == 10

    def test_rounds_up_even_when_the_result_is_just_above_zero(self):
        # 每天 0.1 × 7 = 0.7 → 1，不能是 0
        assert f.forecast_quantity(3, window_days=30, lead_time_days=7) == 1

    def test_no_sales_means_no_forecast(self):
        assert f.forecast_quantity(0, window_days=30, lead_time_days=7) == 0

    def test_a_zero_lead_time_forecasts_nothing(self):
        assert f.forecast_quantity(300, window_days=30, lead_time_days=0) == 0


class TestSuggestedQuantity:
    def test_the_formula_end_to_end(self):
        # 预测 70 + 安全 50 - 可售 60 - 在途 20 = 40
        assert (
            f.suggested_quantity(
                forecast_qty=70, safety_qty=50, available_qty=60, in_transit_qty=20
            )
            == 40
        )

    def test_in_transit_counts_as_covered_stock(self):
        without = f.suggested_quantity(
            forecast_qty=70, safety_qty=50, available_qty=10, in_transit_qty=0
        )
        with_it = f.suggested_quantity(
            forecast_qty=70, safety_qty=50, available_qty=10, in_transit_qty=40
        )
        assert without - with_it == 40
        # 已经在路上的 40 件不该再被当成缺口
        assert with_it == without - 40

    def test_a_negative_result_means_do_not_buy(self):
        assert (
            f.suggested_quantity(
                forecast_qty=10, safety_qty=20, available_qty=500, in_transit_qty=100
            )
            == 0
        )

    def test_exactly_balanced_is_zero_not_one(self):
        assert (
            f.suggested_quantity(
                forecast_qty=30, safety_qty=20, available_qty=30, in_transit_qty=20
            )
            == 0
        )

    def test_negative_safety_is_treated_as_zero(self):
        # 数据脏了也不该给出比真实需求更大的建议量
        assert (
            f.suggested_quantity(
                forecast_qty=10, safety_qty=-100, available_qty=5, in_transit_qty=0
            )
            == 5
        )


class TestLowStockDetection:
    def test_available_below_safety_is_low(self):
        assert (
            f.is_low_stock(available_qty=9, in_transit_qty=0, safety_qty=10) is True
        )

    def test_exactly_at_safety_is_not_low(self):
        # 等于阈值不算缺 —— 否则永远在告警
        assert (
            f.is_low_stock(available_qty=10, in_transit_qty=0, safety_qty=10) is False
        )

    def test_in_transit_prevents_a_false_alarm(self):
        # 可售 3，但在途 50 —— 货在路上，不该报警
        assert (
            f.is_low_stock(available_qty=3, in_transit_qty=50, safety_qty=20) is False
        )

    def test_shortfall_reports_the_gap(self):
        assert f.shortfall(available_qty=3, in_transit_qty=4, safety_qty=20) == 13

    def test_shortfall_is_zero_when_healthy(self):
        assert f.shortfall(available_qty=50, in_transit_qty=0, safety_qty=20) == 0

    def test_zero_safety_never_triggers(self):
        assert f.is_low_stock(available_qty=0, in_transit_qty=0, safety_qty=0) is False
