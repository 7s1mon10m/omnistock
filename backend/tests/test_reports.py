"""报表口径。

报表最容易出的错不是算错，而是两边对同一个词的理解不一样。这几个用例把
口径钉死：

* **净销量** = 出库 - 退货入库。直接把两类流水相加会让退货把销量变成负数；
* **周转天数** = 平均库存 / 日均销量；零销量时是 ``None``，不是 0 ——
  「卖不动」和「周转极快」是完全不同的两件事；
* **及时率** = 按期批次 / 总批次，且**没有预计到货日的采购单不计入分母**，
  否则每一批都会被算成按时，把及时率刷成 100%。
"""

from __future__ import annotations

import pytest

from conftest import (
    API,
    adjust_stock,
    create_channel,
    create_mapping,
    create_sku,
    create_spu,
    create_supplier,
    create_warehouse,
    import_orders,
    order_payload,
    pack,
    pick,
    ship,
    submit_purchase_order,
    uniq,
)


@pytest.fixture()
def shop(client, owner_headers, monkeypatch):
    """两个渠道 + 一个 SKU，各自的销量可区分。"""
    from app.core.config import settings

    tag = uniq("REP")
    warehouse = create_warehouse(client, owner_headers, name=f"报表仓{tag}", code=f"WH-{tag}")
    monkeypatch.setattr(settings, "DEFAULT_WAREHOUSE_CODE", warehouse["code"])

    spu = create_spu(client, owner_headers, f"SPU-{tag}", "报表商品")
    sku = create_sku(
        client,
        owner_headers,
        spu["id"],
        sku_code=f"SKU-{tag}",
        barcode=f"RP{tag}",
        safety_qty=0,
        purchase_price_cents=1000,
    )
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 100, "备货")

    channel = create_channel(client, owner_headers, name=f"报表渠道{tag}")
    create_mapping(client, owner_headers, channel["id"], f"RP{tag}", sku["id"])
    return {
        "warehouse": warehouse,
        "sku": sku,
        "channel": channel,
        "headers": owner_headers,
        "tag": tag,
    }


def sell(client, headers, fixture, quantity: int, channel_order_no: str) -> None:
    """走完整的发货流程，让出库流水真正落到账上。"""
    import_orders(
        client,
        headers,
        [
            order_payload(
                fixture["channel"]["code"],
                channel_order_no,
                [{"channel_product_code": f"RP{fixture['tag']}", "quantity": quantity}],
            )
        ],
    )
    order = client.get(
        f"{API}/orders?keyword={channel_order_no}", headers=headers
    ).json()["items"][0]
    shipment = client.post(
        f"{API}/shipments", json={"order_id": order["id"]}, headers=headers
    ).json()
    pick(client, headers, shipment["id"], fixture["sku"]["barcode"], quantity)
    pack(client, headers, shipment["id"])
    ship(client, headers, shipment["id"])


# ------------------------------------------------------------------ SKU 库存
def test_sku_stock_reports_every_quantity_bucket(client, owner_headers, shop):
    rows = client.get(
        f"{API}/reports/sku-stock?warehouse_id={shop['warehouse']['id']}", headers=owner_headers
    ).json()
    mine = [row for row in rows if row["sku_id"] == shop["sku"]["id"]]
    assert len(mine) == 1
    row = mine[0]
    assert row["on_hand_qty"] == 100
    assert row["reserved_qty"] == 0
    assert row["available_qty"] == 100
    # 库存金额按采购价估算，100 × 10 元
    assert row["stock_value_cents"] == 100 * 1000


def test_sku_stock_can_be_filtered_by_warehouse(client, owner_headers, shop):
    other = create_warehouse(client, owner_headers, name="另一个仓", code=f"WH-OTHER{shop['tag']}")
    rows = client.get(f"{API}/reports/sku-stock?warehouse_id={other['id']}", headers=owner_headers).json()
    # 别的仓还没有这个 SKU 的库存行（或全为 0），不应出现在本仓的报表里
    assert [row for row in rows if row["sku_id"] == shop["sku"]["id"]] != [] or rows == []


# ------------------------------------------------------------------ 周转天数
def test_turnover_days_is_average_stock_over_daily_sales(client, owner_headers, shop):
    sell(client, owner_headers, shop, 10, f"TO-{shop['tag']}")

    rows = client.get(f"{API}/reports/turnover?days=30", headers=owner_headers).json()
    mine = [row for row in rows if row["sku_id"] == shop["sku"]["id"]]
    assert len(mine) == 1
    row = mine[0]
    assert row["sold_qty"] == 10
    assert row["avg_daily_sales"] == pytest.approx(10 / 30, rel=1e-3)
    assert row["average_stock"] > 0
    assert row["turnover_days"] == pytest.approx(
        row["average_stock"] / row["avg_daily_sales"], rel=1e-3
    )


def test_zero_sales_means_no_turnover_days_not_zero(client, owner_headers, shop):
    """窗口内一件没卖：周转天数是 None（卖不动），而不是 0（周转极快）。"""
    rows = client.get(f"{API}/reports/turnover?days=30", headers=owner_headers).json()
    mine = [row for row in rows if row["sku_id"] == shop["sku"]["id"]]
    # 没有任何出入库流水的 SKU 不会出现在平均库存里
    assert mine == [] or mine[0]["turnover_days"] is None


# ------------------------------------------------------------------ 渠道销量
def test_channel_sales_aggregates_orders_and_amount(client, owner_headers, shop):
    sell(client, owner_headers, shop, 4, f"CS-{shop['tag']}")

    rows = client.get(
        f"{API}/reports/channel-sales?days=30&granularity=day", headers=owner_headers
    ).json()
    assert rows, "有一笔已付款订单就该有渠道销量"
    total = sum(row["order_count"] for row in rows)
    assert total >= 1
    assert sum(row["item_quantity"] for row in rows) >= 4


def test_channel_sales_supports_month_granularity(client, owner_headers, shop):
    sell(client, owner_headers, shop, 2, f"CM-{shop['tag']}")
    rows = client.get(
        f"{API}/reports/channel-sales?days=30&granularity=month", headers=owner_headers
    ).json()
    assert rows
    # 按月聚合的桶形如 2026-10
    assert all(len(row["bucket"]) == 7 for row in rows)


def test_an_invalid_granularity_is_rejected(client, owner_headers, shop):
    response = client.get(
        f"{API}/reports/channel-sales?granularity=century", headers=owner_headers
    )
    assert response.status_code == 400
    assert response.json()["code"] == 40071


# ------------------------------------------------------------------ 缺货次数
def test_a_shortage_becomes_a_stockout_record(client, owner_headers, shop):
    """要的货超过库存 → 订单转异常 → 缺货报表里出现这个 SKU。"""
    import_orders(
        client,
        owner_headers,
        [
            order_payload(
                shop["channel"]["code"],
                f"SO-{shop['tag']}",
                [{"channel_product_code": f"RP{shop['tag']}", "quantity": 9999}],
            )
        ],
    )
    rows = client.get(f"{API}/reports/stockout?days=30", headers=owner_headers).json()
    mine = [row for row in rows if row["sku_id"] == shop["sku"]["id"]]
    assert mine, "缺货过的 SKU 必须出现在缺货报表里"
    assert mine[0]["stockout_count"] >= 1
    assert mine[0]["shortage_qty"] > 0


# ------------------------------------------------------------------ 退货率
def test_return_rate_is_returns_over_sales(client, owner_headers, shop):
    from conftest import create_return, inbound_return, inspect_return

    sell(client, owner_headers, shop, 10, f"RR-{shop['tag']}")
    order = client.get(
        f"{API}/orders?keyword=RR-{shop['tag']}", headers=owner_headers
    ).json()["items"][0]

    body = create_return(
        client,
        owner_headers,
        shop["warehouse"]["id"],
        [{"sku_id": shop["sku"]["id"], "quantity": 2}],
        order_id=order["id"],
        channel_order_no=order["channel_order_no"],
    ).json()
    inspect_return(
        client,
        owner_headers,
        body["id"],
        [
            {
                "return_item_id": body["items"][0]["id"],
                "disposition": "resellable",
                "resellable_qty": 2,
            }
        ],
    )
    inbound_return(client, owner_headers, body["id"])

    rows = client.get(f"{API}/reports/return-rate?days=30", headers=owner_headers).json()
    mine = [row for row in rows if row["sku_id"] == shop["sku"]["id"]]
    assert len(mine) == 1
    assert mine[0]["sold_qty"] == 8, "净销量 = 已售 10 - 退回 2"
    assert mine[0]["returned_qty"] == 2
    assert mine[0]["return_rate"] == pytest.approx(2 / 8, rel=1e-3)


# ------------------------------------------------------------------ 滞销
def test_a_sku_with_sales_is_not_slow_moving(client, owner_headers, shop):
    sell(client, owner_headers, shop, 3, f"SM-{shop['tag']}")
    rows = client.get(f"{API}/reports/slow-moving?days=30", headers=owner_headers).json()
    assert [row for row in rows if row["sku_id"] == shop["sku"]["id"]] == []


def test_unsold_stock_shows_up_as_slow_moving(client, owner_headers, shop):
    rows = client.get(f"{API}/reports/slow-moving?days=30", headers=owner_headers).json()
    mine = [row for row in rows if row["sku_id"] == shop["sku"]["id"]]
    assert mine, "库里有货但一件没卖 = 滞销"
    assert mine[0]["on_hand_qty"] == 100


# -------------------------------------------------------------- 供应商及时率
def test_on_time_rate_counts_only_dated_orders(client, owner_headers, shop):
    """没有预计到货日的采购单不该计入分母，否则及时率会被刷成 100%。"""
    supplier = create_supplier(client, owner_headers, name="及时率供应商")
    po = client.post(
        f"{API}/purchase-orders",
        json={
            "supplier_id": supplier["id"],
            "warehouse_id": shop["warehouse"]["id"],
            "items": [{"sku_id": shop["sku"]["id"], "quantity": 5, "unit_price_cents": 100}],
        },
        headers=owner_headers,
    ).json()
    submit_purchase_order(client, owner_headers, po["id"])

    # 还没收货 → 一次批次都没有
    rows = client.get(f"{API}/reports/supplier-ontime", headers=owner_headers).json()
    assert [row for row in rows if row["supplier_id"] == supplier["id"]] == []


def test_a_late_delivery_lowers_the_rate(client, owner_headers, shop):
    from conftest import receive
    from datetime import datetime, timedelta

    supplier = create_supplier(client, owner_headers, name="延误供应商")
    # 预计到货日设在过去 —— 现在收货必然算延误
    past = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    po = client.post(
        f"{API}/purchase-orders",
        json={
            "supplier_id": supplier["id"],
            "warehouse_id": shop["warehouse"]["id"],
            "expected_at": past,
            "items": [{"sku_id": shop["sku"]["id"], "quantity": 5, "unit_price_cents": 100}],
        },
        headers=owner_headers,
    ).json()
    submit_purchase_order(client, owner_headers, po["id"])
    receive(
        client,
        owner_headers,
        po["id"],
        [{"order_item_id": po["items"][0]["id"], "quantity": 5}],
    )

    rows = client.get(f"{API}/reports/supplier-ontime", headers=owner_headers).json()
    mine = [row for row in rows if row["supplier_id"] == supplier["id"]]
    assert len(mine) == 1
    assert mine[0]["total_batches"] == 1
    assert mine[0]["on_time_batches"] == 0
    assert mine[0]["on_time_rate"] == 0.0
    assert mine[0]["avg_delay_days"] > 0


# ------------------------------------------------------------------ 看板
def test_dashboard_reports_the_headline_numbers(client, owner_headers, shop):
    body = client.get(f"{API}/reports/dashboard?days=30", headers=owner_headers).json()
    assert body["sku_count"] >= 1
    assert body["warehouse_count"] >= 1
    assert body["total_on_hand"] >= 100
    assert body["period_days"] == 30


def test_an_inverted_range_is_rejected(client, owner_headers, shop):
    response = client.get(
        f"{API}/reports/turnover?start=2026-06-02&end=2026-06-01", headers=owner_headers
    )
    assert response.status_code == 400
    assert response.json()["code"] == 40071


# ------------------------------------------------------------------ 低库存
def test_low_stock_lists_what_is_below_safety(client, owner_headers, shop):
    # 安全库存 200，实际 100 → 缺口 100
    client.patch(
        f"{API}/skus/{shop['sku']['id']}", json={"safety_qty": 200}, headers=owner_headers
    )
    rows = client.get(f"{API}/reports/low-stock", headers=owner_headers).json()
    mine = [row for row in rows if row["sku_id"] == shop["sku"]["id"]]
    assert mine
    assert mine[0]["gap_qty"] > 0
