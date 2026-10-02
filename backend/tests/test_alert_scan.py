"""预警扫描、去重与补货建议。

这个文件守的是 M6 最容易被做错的地方：**重复告警**。

一个每小时跑一次的扫描，遇到一个长期低于安全库存的 SKU，如果不做去重，
一天会刷出 24 条预警。真正的做法是「未解决就只留一条」，补货到位后自动
关闭、再次缺货才重新告警。

所有扫描与生成都限定在**本用例自己的仓库 / SKU** 上：测试共享同一个数据库，
全库扫描会把别的用例留下的库存行算进来，得到的是一个不断漂移的数字。
"""

from __future__ import annotations

import pytest

from conftest import (
    API,
    ack_alert,
    ensure_alert_rule,
    adjust_stock,
    create_alert_rule,
    create_sku,
    create_spu,
    create_supplier,
    create_warehouse,
    generate_suggestions,
    list_alerts,
    scan_alerts,
    to_purchase_order,
    uniq,
)


def alerts_for(client, headers, sku_id: int) -> list[dict]:
    """只看这个 SKU 的预警 —— 整库 total 会把别的用例留下的告警算进来。"""
    return list_alerts(client, headers, sku_id=sku_id)["items"]


@pytest.fixture()
def rule(client, owner_headers, low_stock):
    """给当前 SKU 一条阈值 10 的规则。

    刻意用 ``scope=sku`` 而不是 ``scope=global``：全局规则会影响数据库里所有
    SKU，一个用例建了就会污染后面每一个用例的断言。绑定 SKU 则每次都独立。
    """
    return ensure_alert_rule(
        client,
        owner_headers,
        name="阈值10",
        scope="sku",
        sku_id=low_stock["sku"]["id"],
        threshold_qty=10,
    )


# ------------------------------------------------------------------ 规则
def test_a_global_rule_can_be_created(client, owner_headers, low_stock):
    """全局规则能建，但用完即删 —— 它会命中库里每一个 SKU。"""
    response = create_alert_rule(
        client, owner_headers, name="全局低库存", scope="global", threshold_qty=10
    )
    assert response.status_code == 201, response.text
    body = response.json()
    try:
        assert body["scope"] == "global"
        assert body["threshold_qty"] == 10
        assert body["enabled"] is True
    finally:
        client.delete(f"{API}/alert-rules/{body['id']}", headers=owner_headers)


def test_the_same_scope_cannot_have_two_rules(client, owner_headers, low_stock):
    sku = low_stock["sku"]
    first = create_alert_rule(
        client, owner_headers, name="第一条", scope="sku", sku_id=sku["id"], threshold_qty=7
    )
    assert first.status_code == 201
    second = create_alert_rule(
        client, owner_headers, name="第二条", scope="sku", sku_id=sku["id"], threshold_qty=8
    )
    assert second.status_code == 409
    assert second.json()["code"] == 40970


def test_a_sku_rule_needs_a_sku(client, owner_headers, low_stock):
    response = create_alert_rule(client, owner_headers, name="空规则", scope="sku")
    assert response.status_code == 400


def test_a_sku_rule_may_not_carry_a_warehouse(client, owner_headers, low_stock):
    response = create_alert_rule(
        client,
        owner_headers,
        name="串了",
        scope="sku",
        sku_id=low_stock["sku"]["id"],
        warehouse_id=low_stock["warehouse"]["id"],
    )
    assert response.status_code == 400


def test_different_scopes_coexist(client, owner_headers, low_stock, rule):
    assert rule["scope"] == "sku"
    assert (
        create_alert_rule(
            client,
            owner_headers,
            name="按仓",
            scope="warehouse",
            warehouse_id=low_stock["warehouse"]["id"],
        ).status_code
        == 201
    )


def test_only_an_admin_may_touch_rules(client, operator_headers, low_stock):
    assert create_alert_rule(client, operator_headers).status_code == 403


def test_a_rule_can_be_edited(client, owner_headers, rule):
    response = client.put(
        f"{API}/alert-rules/{rule['id']}", json={"threshold_qty": 3}, headers=owner_headers
    )
    assert response.status_code == 200
    assert response.json()["threshold_qty"] == 3


# ------------------------------------------------------------------ 扫描
def test_a_below_safety_row_raises_one_alert(client, owner_headers, low_stock, rule, wh):
    result = scan_alerts(client, owner_headers, warehouse_id=wh)
    assert result["alerts_created"] == 1

    alert = alerts_for(client, owner_headers, low_stock["sku"]["id"])[0]
    assert alert["type"] == "low_stock"
    assert alert["status"] == "open"
    assert alert["safety_qty"] == 10, "规则阈值覆盖了 SKU 自己的安全库存"
    assert alert["available_qty"] == 5
    assert alert["gap_qty"] == 5


def test_without_a_rule_the_skus_own_safety_stock_applies(client, owner_headers, low_stock, wh):
    scan_alerts(client, owner_headers, warehouse_id=wh)
    assert list_alerts(client, owner_headers)["items"][0]["safety_qty"] == 20


def test_a_global_rule_covers_every_sku(client, owner_headers, low_stock, wh):
    """全局规则是兜底：没给 SKU 单独立规则时，它对全库生效。

    用完必须删掉 —— 否则它会影响之后每一个用例的阈值判断。
    """
    created = create_alert_rule(
        client, owner_headers, name="全局兜底", scope="global", threshold_qty=12
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    try:
        scan_alerts(client, owner_headers, warehouse_id=wh)
        assert alerts_for(client, owner_headers, low_stock["sku"]["id"])[0]["safety_qty"] == 12
    finally:
        client.delete(f"{API}/alert-rules/{rule_id}", headers=owner_headers)


def test_a_rule_threshold_overrides_the_sku_safety_qty(client, owner_headers, low_stock, wh):
    # 可售 5 高于规则的 3 —— 宽阈值下不该告警
    ensure_alert_rule(
        client,
        owner_headers,
        name="宽阈值",
        scope="sku",
        sku_id=low_stock["sku"]["id"],
        threshold_qty=3,
    )
    result = scan_alerts(client, owner_headers, warehouse_id=wh)
    assert result["alerts_created"] == 0


def test_a_narrow_rule_wins_over_a_broad_one(client, owner_headers, low_stock, wh):
    ensure_alert_rule(
        client, owner_headers, name="按仓", scope="warehouse",
        warehouse_id=wh, threshold_qty=1,
    )
    ensure_alert_rule(
        client,
        owner_headers,
        name="按 SKU",
        scope="sku",
        sku_id=low_stock["sku"]["id"],
        threshold_qty=50,
    )
    scan_alerts(client, owner_headers, warehouse_id=wh)
    assert alerts_for(client, owner_headers, low_stock["sku"]["id"])[0]["safety_qty"] == 50


def test_rescanning_does_not_duplicate_an_unresolved_alert(client, owner_headers, low_stock, rule, wh):
    scan_alerts(client, owner_headers, warehouse_id=wh)

    # 模拟 cron 每小时跑一次：跑 5 次，只应该有一条预警
    for _ in range(5):
        scan_alerts(client, owner_headers, warehouse_id=wh)
    assert len(alerts_for(client, owner_headers, low_stock["sku"]["id"])) == 1


def test_an_acknowledged_alert_still_blocks_duplicates(client, owner_headers, low_stock, rule, wh):
    scan_alerts(client, owner_headers, warehouse_id=wh)
    alert_id = alerts_for(client, owner_headers, low_stock["sku"]["id"])[0]["id"]

    assert ack_alert(client, owner_headers, alert_id).json()["status"] == "acked"
    scan_alerts(client, owner_headers, warehouse_id=wh)
    assert len(alerts_for(client, owner_headers, low_stock["sku"]["id"])) == 1


def test_acknowledging_twice_is_harmless(client, owner_headers, low_stock, rule, wh):
    scan_alerts(client, owner_headers, warehouse_id=wh)
    alert_id = alerts_for(client, owner_headers, low_stock["sku"]["id"])[0]["id"]

    first = ack_alert(client, owner_headers, alert_id, remark="已知悉")
    second = ack_alert(client, owner_headers, alert_id)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "acked"
    # 第一次写下的备注不该被第二次覆盖掉
    assert "已知悉" in second.json()["message"]


def test_restocking_resolves_the_alert_and_frees_the_key(
    client, owner_headers, rule, wh, sku_id
):
    scan_alerts(client, owner_headers, warehouse_id=wh)

    adjust_stock(client, owner_headers, sku_id, wh, 50, "补货")
    result = scan_alerts(client, owner_headers, warehouse_id=wh)
    assert result["resolved"] == 1
    assert alerts_for(client, owner_headers, sku_id)[0]["status"] == "resolved"

    # 再次缺货时必须能重新告警，否则这条 SKU 就被永久静音了
    # 回到可售 5（阈值 10 以下）：再次缺货必须能重新告警
    adjust_stock(client, owner_headers, sku_id, wh, -50, "又卖光")
    assert scan_alerts(client, owner_headers, warehouse_id=wh)["alerts_created"] == 1
    assert len(alerts_for(client, owner_headers, sku_id)) == 2


def test_stock_arriving_closes_the_alert(client, owner_headers, rule, wh, sku_id):
    scan_alerts(client, owner_headers, warehouse_id=wh)
    adjust_stock(client, owner_headers, sku_id, wh, 50, "采购到货")
    assert scan_alerts(client, owner_headers, warehouse_id=wh)["resolved"] == 1


def test_a_sku_with_zero_safety_is_never_flagged(client, owner_headers, rule):
    tag = uniq("SAFE")
    warehouse = create_warehouse(client, owner_headers, name=f"无安全{tag}", code=f"WH-{tag}")
    spu = create_spu(client, owner_headers, f"SPU-{tag}", "无安全库存")
    sku = create_sku(client, owner_headers, spu["id"], sku_code=f"SKU-{tag}", safety_qty=0)

    scan_alerts(client, owner_headers, warehouse_id=warehouse["id"])
    assert alerts_for(client, owner_headers, sku["id"]) == []


def test_an_empty_shelf_raises_the_more_severe_type(client, owner_headers):
    """可售已经跌到 0 或以下 —— 这不是「快没了」，是「已经没了」。"""
    tag = uniq("ZERO")
    warehouse = create_warehouse(client, owner_headers, name=f"断货{tag}", code=f"WH-{tag}")
    spu = create_spu(client, owner_headers, f"SPU-{tag}", "断货商品")
    sku = create_sku(client, owner_headers, spu["id"], sku_code=f"SKU-{tag}", safety_qty=10)
    ensure_alert_rule(
        client, owner_headers, name="断货阈值", scope="warehouse",
        warehouse_id=warehouse["id"], threshold_qty=5,
    )

    scan_alerts(client, owner_headers, warehouse_id=warehouse["id"])
    mine = alerts_for(client, owner_headers, sku["id"])
    assert len(mine) == 1
    assert mine[0]["type"] == "out_of_stock"

    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 20, "紧急补货")
    assert scan_alerts(client, owner_headers, warehouse_id=warehouse["id"])["resolved"] >= 1


def test_acknowledging_a_resolved_alert_is_refused(client, owner_headers, low_stock, rule, wh):
    scan_alerts(client, owner_headers, warehouse_id=wh)
    alert_id = alerts_for(client, owner_headers, low_stock["sku"]["id"])[0]["id"]
    client.post(f"{API}/alerts/{alert_id}/resolve", headers=owner_headers)
    assert ack_alert(client, owner_headers, alert_id).status_code == 409


# ---------------------------------------------------------------- 补货建议
def test_a_suggestion_equals_forecast_plus_safety_minus_covered(
    client, owner_headers, wh, sku_id
):
    # 可售 5、安全 20、最近没卖出过 → 预测 0 → 建议 0 + 20 - 5 - 0 = 15
    created = generate_suggestions(client, owner_headers, warehouse_id=wh, sku_id=sku_id)
    assert len(created) == 1
    row = created[0]
    assert row["suggested_qty"] == 15
    assert row["forecast_qty"] == 0
    assert row["safety_qty"] == 20
    assert row["available_qty"] == 5


def test_no_suggestion_when_stock_is_ample(client, owner_headers):
    tag = uniq("RICH")
    warehouse = create_warehouse(client, owner_headers, name=f"充足{tag}", code=f"WH-{tag}")
    spu = create_spu(client, owner_headers, f"SPU-{tag}", "库存充足")
    sku = create_sku(client, owner_headers, spu["id"], sku_code=f"SKU-{tag}", safety_qty=10)
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 500, "充足备货")

    assert generate_suggestions(
        client, owner_headers, warehouse_id=warehouse["id"], sku_id=sku["id"]
    ) == []


def test_more_stock_reduces_the_suggested_quantity(client, owner_headers, wh, sku_id):
    first = generate_suggestions(client, owner_headers, warehouse_id=wh, sku_id=sku_id)[0]
    assert first["suggested_qty"] == 15
    assert first["available_qty"] == 5

    client.post(f"{API}/replenishment-suggestions/{first['id']}/dismiss", headers=owner_headers)
    # 补进 10 件，缺口从 15 降到 5
    adjust_stock(client, owner_headers, sku_id, wh, 10, "采购到货")

    second = generate_suggestions(client, owner_headers, warehouse_id=wh, sku_id=sku_id)[0]
    assert second["available_qty"] == 15
    assert second["suggested_qty"] == 5


def test_regenerating_does_not_duplicate_an_open_suggestion(
    client, owner_headers, wh, sku_id
):
    once = generate_suggestions(client, owner_headers, warehouse_id=wh, sku_id=sku_id)
    twice = generate_suggestions(client, owner_headers, warehouse_id=wh, sku_id=sku_id)
    assert len(once) == 1
    assert twice == []


def test_a_suggestion_becomes_a_draft_purchase_order(
    client, owner_headers, wh, sku_id, buyer_headers
):
    supplier = create_supplier(client, owner_headers, name="补货供应商")
    suggestion = generate_suggestions(
        client, buyer_headers, warehouse_id=wh, sku_id=sku_id
    )[0]

    response = to_purchase_order(
        client, buyer_headers, suggestion["id"], supplier_id=supplier["id"]
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["purchase_order"]["status"] == "draft", "建议只是数字，不该直接下单"
    assert body["purchase_order"]["items"][0]["quantity"] == suggestion["suggested_qty"]
    assert body["suggestion"]["status"] == "converted"


def test_a_converted_suggestion_cannot_be_converted_again(
    client, owner_headers, wh, sku_id, buyer_headers
):
    supplier = create_supplier(client, owner_headers, name="补货供应商")
    suggestion = generate_suggestions(
        client, buyer_headers, warehouse_id=wh, sku_id=sku_id
    )[0]
    to_purchase_order(client, buyer_headers, suggestion["id"], supplier_id=supplier["id"])

    again = to_purchase_order(
        client, buyer_headers, suggestion["id"], supplier_id=supplier["id"]
    )
    assert again.status_code == 409


def test_a_conversion_frees_the_key_for_the_next_round(
    client, owner_headers, wh, sku_id, buyer_headers
):
    """转成采购单后必须能重新评估，否则 UNIQUE(dedup_key) 会挡住新建议。"""
    supplier = create_supplier(client, owner_headers, name="补货供应商")
    suggestion = generate_suggestions(
        client, buyer_headers, warehouse_id=wh, sku_id=sku_id
    )[0]
    to_purchase_order(client, buyer_headers, suggestion["id"], supplier_id=supplier["id"])

    again = generate_suggestions(client, buyer_headers, warehouse_id=wh, sku_id=sku_id)
    assert again != []


def test_converting_without_a_supplier_is_refused(
    client, owner_headers, wh, sku_id, buyer_headers
):
    suggestion = generate_suggestions(
        client, buyer_headers, warehouse_id=wh, sku_id=sku_id
    )[0]
    response = to_purchase_order(client, buyer_headers, suggestion["id"])
    assert response.status_code == 400
    assert "供应商" in response.json()["message"]


def test_the_warehouse_role_cannot_create_purchase_orders(
    client, owner_headers, wh, sku_id, buyer_headers, warehouse_headers
):
    """建采购单是买手的活；仓管能看建议，但不能把建议变成采购单。"""
    supplier = create_supplier(client, owner_headers, name="代建")
    suggestion = generate_suggestions(
        client, buyer_headers, warehouse_id=wh, sku_id=sku_id
    )[0]
    response = to_purchase_order(
        client, warehouse_headers, suggestion["id"], supplier_id=supplier["id"]
    )
    assert response.status_code == 403
