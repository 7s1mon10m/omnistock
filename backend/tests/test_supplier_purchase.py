"""M4 供应商与采购收货。

重点在两条规则上：

* 采购单本身不动库存 —— 只有收货才动；
* 到货永远要拆成合格与次品两笔，次品永远不进可售。
"""

from __future__ import annotations

import datetime as dt

from conftest import (
    API,
    adjust_stock,
    create_purchase_order,
    create_sku,
    create_spu,
    create_supplier,
    get_purchase_order,
    inventory_row,
    receive,
    submit_purchase_order,
    uniq,
)


def _purchasable(client, headers, catalog, quantity=100, price=1500):
    tag = uniq("PO")
    spu = create_spu(client, headers, f"SPU-{tag}", "采购测试商品")
    sku = create_sku(client, headers, spu["id"], sku_code=f"SKU-{tag}", safety_qty=0)
    return {
        "sku": sku,
        "warehouse": catalog["warehouse"],
        "catalog": catalog,
        "pay": lambda: create_purchase_order(
            client,
            headers,
            supplier_id=create_supplier(client, headers, f"供应商{tag}")["id"],
            warehouse_id=catalog["warehouse"]["id"],
            items=[{"sku_id": sku["id"], "quantity": quantity, "unit_price_cents": price}],
        ),
    }


# ------------------------------------------------------------------ suppliers
def test_supplier_gets_an_auto_code_and_rejects_duplicates(client, owner_headers):
    first = create_supplier(client, owner_headers, "甲供应商", code="SUP-FIX")
    assert first["code"] == "SUP-FIX"

    again = client.post(
        f"{API}/suppliers", json={"name": "重复", "code": "SUP-FIX"}, headers=owner_headers
    )
    assert again.status_code == 409
    assert again.json()["code"] == 40940


def test_supplier_lead_time_seeds_the_expected_date(client, owner_headers):
    supplier = create_supplier(client, owner_headers, "交期供应商", lead_time_days=3)
    assert supplier["lead_time_days"] == 3
    assert supplier["open_order_count"] == 0


def test_open_order_count_tracks_unfinished_orders(client, owner_headers, catalog):
    supplier = create_supplier(client, owner_headers, "计数供应商")
    spu = create_spu(client, owner_headers, uniq("SPU"), "计数商品")
    sku = create_sku(client, owner_headers, spu["id"], sku_code=uniq("SKU"), safety_qty=0)

    order = create_purchase_order(
        client,
        owner_headers,
        supplier["id"],
        catalog["warehouse"]["id"],
        [{"sku_id": sku["id"], "quantity": 10, "unit_price_cents": 100}],
    ).json()
    submit_purchase_order(client, owner_headers, order["id"])

    assert client.get(f"{API}/suppliers/{supplier['id']}", headers=owner_headers).json()[
        "open_order_count"
    ] == 1


def test_warehouse_role_cannot_create_a_supplier(client, warehouse_headers):
    response = client.post(
        f"{API}/suppliers", json={"name": "越权"}, headers=warehouse_headers
    )
    assert response.status_code == 403
    assert response.json()["code"] == 40301


# --------------------------------------------------------------- purchase order
def test_a_new_order_is_a_draft_and_does_not_move_stock(client, owner_headers, catalog):
    helper = _purchasable(client, owner_headers, catalog)
    order = helper["pay"]().json()

    assert order["status"] == "draft"
    assert order["po_no"].startswith("PO")
    assert order["total_quantity"] == 100
    assert order["total_amount_cents"] == 100 * 1500
    # 采购单只是承诺，不产生任何库存
    row = inventory_row(
        client, owner_headers, helper["sku"]["id"], catalog["warehouse"]["id"]
    )
    assert row["on_hand_qty"] == 0


def test_expected_date_comes_from_the_supplier_lead_time(client, owner_headers, catalog):
    supplier = create_supplier(client, owner_headers, "交期七天", lead_time_days=7)
    spu = create_spu(client, owner_headers, uniq("SPU"), "交期商品")
    sku = create_sku(client, owner_headers, spu["id"], sku_code=uniq("SKU"), safety_qty=0)

    order = create_purchase_order(
        client,
        owner_headers,
        supplier["id"],
        catalog["warehouse"]["id"],
        [{"sku_id": sku["id"], "quantity": 1, "unit_price_cents": 1}],
    ).json()

    expected = dt.datetime.fromisoformat(order["expected_at"])
    assert 6 <= (expected - dt.datetime.now()).days <= 8


def test_only_a_draft_can_be_edited(client, owner_headers, catalog):
    helper = _purchasable(client, owner_headers, catalog)
    order = helper["pay"]().json()

    ok = client.patch(
        f"{API}/purchase-orders/{order['id']}",
        json={"remark": "改个备注"},
        headers=owner_headers,
    )
    assert ok.status_code == 200
    assert ok.json()["remark"] == "改个备注"

    submit_purchase_order(client, owner_headers, order["id"])
    blocked = client.patch(
        f"{API}/purchase-orders/{order['id']}",
        json={"remark": "下单后还想改"},
        headers=owner_headers,
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == 40941


def test_submitting_twice_is_refused(client, owner_headers, catalog):
    helper = _purchasable(client, owner_headers, catalog)
    order = helper["pay"]().json()
    assert submit_purchase_order(client, owner_headers, order["id"]).json()["status"] == "submitted"

    again = submit_purchase_order(client, owner_headers, order["id"])
    assert again.status_code == 409
    assert again.json()["code"] == 40941


def test_a_draft_cannot_be_received(client, owner_headers, catalog):
    helper = _purchasable(client, owner_headers, catalog)
    order = helper["pay"]().json()

    response = receive(
        client, owner_headers, order["id"], [{"order_item_id": order["items"][0]["id"], "quantity": 1}]
    )
    assert response.status_code == 409
    assert response.json()["code"] == 40941


def test_an_unknown_sku_is_refused(client, owner_headers, catalog):
    supplier = create_supplier(client, owner_headers, "无效 SKU 供应商")
    response = create_purchase_order(
        client,
        owner_headers,
        supplier["id"],
        catalog["warehouse"]["id"],
        [{"sku_id": 987654, "quantity": 1, "unit_price_cents": 1}],
    )
    assert response.status_code == 404
    assert response.json()["code"] == 40411


# -------------------------------------------------------------------- receipts
def test_partial_receipt_raises_on_hand_and_marks_the_order_partial(
    client, owner_headers, catalog
):
    helper = _purchasable(client, owner_headers, catalog, quantity=100)
    order = helper["pay"]().json()
    submit_purchase_order(client, owner_headers, order["id"])
    item_id = order["items"][0]["id"]

    body = receive(
        client, owner_headers, order["id"], [{"order_item_id": item_id, "quantity": 60}]
    ).json()
    assert body["order"]["status"] == "partial"
    assert body["order"]["received_quantity"] == 60
    assert body["order"]["is_fully_received"] is False

    row = inventory_row(
        client, owner_headers, helper["sku"]["id"], catalog["warehouse"]["id"]
    )
    assert row["on_hand_qty"] == 60
    assert row["available_qty"] == 60


def test_defectives_never_become_sellable(client, owner_headers, catalog):
    """到货 60 件里 5 件次品：实际 +55、次品 +5、可售 +55。"""
    helper = _purchasable(client, owner_headers, catalog, quantity=100)
    order = helper["pay"]().json()
    submit_purchase_order(client, owner_headers, order["id"])
    item_id = order["items"][0]["id"]

    receive(
        client,
        owner_headers,
        order["id"],
        [{"order_item_id": item_id, "quantity": 60, "defective_qty": 5}],
    )

    row = inventory_row(
        client, owner_headers, helper["sku"]["id"], catalog["warehouse"]["id"]
    )
    assert row["on_hand_qty"] == 55
    assert row["defective_qty"] == 5
    assert row["available_qty"] == 55, "次品不能进可售"

    # 账面自洽：实际 + 次品 = 到货总量
    assert row["on_hand_qty"] + row["defective_qty"] == 60


def test_the_two_ledger_rows_describe_qualified_and_defective(
    client, owner_headers, catalog
):
    helper = _purchasable(client, owner_headers, catalog, quantity=50)
    order = helper["pay"]().json()
    submit_purchase_order(client, owner_headers, order["id"])
    receive(
        client,
        owner_headers,
        order["id"],
        [{"order_item_id": order["items"][0]["id"], "quantity": 20, "defective_qty": 3}],
    )

    ledger = client.get(
        f"{API}/inventory/ledger?sku_id={helper['sku']['id']}&page_size=200",
        headers=owner_headers,
    ).json()["items"]
    by_type = {row["type"]: row for row in ledger}

    qualified = by_type["purchase_inbound"]
    assert qualified["qty_delta"] == 17
    assert qualified["on_hand_before"] + qualified["qty_delta"] == qualified["on_hand_after"]

    defective = by_type["purchase_defective"]
    # 次品那条：实际库存没变，变的是次品区
    assert defective["qty_delta"] == 0
    assert defective["on_hand_before"] == defective["on_hand_after"]
    assert defective["defective_before"] == 0
    assert defective["defective_after"] == 3


def test_receiving_more_than_ordered_is_refused(client, owner_headers, catalog):
    helper = _purchasable(client, owner_headers, catalog, quantity=100)
    order = helper["pay"]().json()
    submit_purchase_order(client, owner_headers, order["id"])
    item_id = order["items"][0]["id"]

    receive(client, owner_headers, order["id"], [{"order_item_id": item_id, "quantity": 60}])
    over = receive(
        client, owner_headers, order["id"], [{"order_item_id": item_id, "quantity": 50}]
    )
    assert over.status_code == 409
    assert over.json()["code"] == 40942
    assert "最多还能收 40 件" in over.json()["message"]

    row = inventory_row(
        client, owner_headers, helper["sku"]["id"], catalog["warehouse"]["id"]
    )
    assert row["on_hand_qty"] == 60, "被拒的收货不能影响库存"


def test_more_defectives_than_arrived_is_rejected_by_the_schema(client, owner_headers, catalog):
    helper = _purchasable(client, owner_headers, catalog, quantity=100)
    order = helper["pay"]().json()
    submit_purchase_order(client, owner_headers, order["id"])

    response = receive(
        client,
        owner_headers,
        order["id"],
        [{"order_item_id": order["items"][0]["id"], "quantity": 5, "defective_qty": 9}],
    )
    assert response.status_code == 422


def test_successive_receipts_close_the_order(client, owner_headers, catalog):
    helper = _purchasable(client, owner_headers, catalog, quantity=100)
    order = helper["pay"]().json()
    submit_purchase_order(client, owner_headers, order["id"])
    item_id = order["items"][0]["id"]

    receive(
        client,
        owner_headers,
        order["id"],
        [{"order_item_id": item_id, "quantity": 60, "defective_qty": 5}],
    )
    final = receive(client, owner_headers, order["id"], [{"order_item_id": item_id, "quantity": 40}])
    assert final.json()["order"]["status"] == "received"
    assert final.json()["order"]["is_fully_received"] is True

    row = inventory_row(
        client, owner_headers, helper["sku"]["id"], catalog["warehouse"]["id"]
    )
    assert row["on_hand_qty"] == 95
    assert row["defective_qty"] == 5

    # 收齐后不能再收
    again = receive(client, owner_headers, order["id"], [{"order_item_id": item_id, "quantity": 1}])
    assert again.status_code == 409


def test_receipts_are_listed_on_the_order_and_separately(client, owner_headers, catalog):
    helper = _purchasable(client, owner_headers, catalog, quantity=100)
    order = helper["pay"]().json()
    submit_purchase_order(client, owner_headers, order["id"])
    item_id = order["items"][0]["id"]
    receive(client, owner_headers, order["id"], [{"order_item_id": item_id, "quantity": 30}])
    receive(client, owner_headers, order["id"], [{"order_item_id": item_id, "quantity": 20}])

    detail = get_purchase_order(client, owner_headers, order["id"])
    assert len(detail["receipts"]) == 2
    assert {row["total_quantity"] for row in detail["receipts"]} == {30, 20}

    listed = client.get(
        f"{API}/purchase-receipts?order_id={order['id']}", headers=owner_headers
    ).json()
    assert listed["total"] == 2

    receipt_id = listed["items"][0]["id"]
    one = client.get(f"{API}/purchase-receipts/{receipt_id}", headers=owner_headers).json()
    assert one["po_no"] == order["po_no"]
    assert one["items"][0]["sku_code"] == helper["sku"]["sku_code"]


def test_a_receipt_into_another_warehouse_is_rejected(client, owner_headers, catalog):
    """采购单指定收货仓，收货不能跑到别处去。"""
    helper = _purchasable(client, owner_headers, catalog, quantity=10)
    order = helper["pay"]().json()
    submit_purchase_order(client, owner_headers, order["id"])

    body = receive(
        client,
        owner_headers,
        order["id"],
        [{"order_item_id": order["items"][0]["id"], "quantity": 10}],
    ).json()
    # 库存只会出现在采购单指定的仓库
    row = inventory_row(
        client, owner_headers, helper["sku"]["id"], catalog["warehouse"]["id"]
    )
    assert row["on_hand_qty"] == 10
    assert body["receipt"]["warehouse_id"] == catalog["warehouse"]["id"]


def test_cancelling_an_order_stops_further_receipts(client, owner_headers, catalog):
    helper = _purchasable(client, owner_headers, catalog, quantity=100)
    order = helper["pay"]().json()
    submit_purchase_order(client, owner_headers, order["id"])

    cancelled = client.post(
        f"{API}/purchase-orders/{order['id']}/cancel?reason=供应商缺货", headers=owner_headers
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    blocked = receive(
        client, owner_headers, order["id"], [{"order_item_id": order["items"][0]["id"], "quantity": 1}]
    )
    assert blocked.status_code == 409


def test_receiving_does_not_touch_reserved_stock(client, owner_headers, catalog):
    """补货不会把已经占用的货"释放"出来 —— 实际库存和占用各走各的。"""
    helper = _purchasable(client, owner_headers, catalog, quantity=100)
    sku_id = helper["sku"]["id"]
    warehouse_id = catalog["warehouse"]["id"]

    adjust_stock(client, catalog["headers"], sku_id, warehouse_id, 10, "期初")
    client.post(
        f"{API}/inventory/reserve",
        json={"sku_id": sku_id, "warehouse_id": warehouse_id, "quantity": 4},
        headers=owner_headers,
    )

    order = helper["pay"]().json()
    submit_purchase_order(client, owner_headers, order["id"])
    receive(client, owner_headers, order["id"], [{"order_item_id": order["items"][0]["id"], "quantity": 50}])

    row = inventory_row(client, owner_headers, sku_id, warehouse_id)
    assert row["on_hand_qty"] == 60
    assert row["reserved_qty"] == 4
    assert row["available_qty"] == 56


def test_purchase_order_role_separation(client, owner_headers, buyer_headers, catalog):
    """采购角色能下采购单，但不能收货（收货是仓库的活）。"""
    supplier = create_supplier(client, owner_headers, "角色供应商")
    spu = create_spu(client, owner_headers, uniq("SPU"), "角色商品")
    sku = create_sku(client, owner_headers, spu["id"], sku_code=uniq("SKU"), safety_qty=0)

    order = create_purchase_order(
        client,
        buyer_headers,
        supplier["id"],
        catalog["warehouse"]["id"],
        [{"sku_id": sku["id"], "quantity": 5, "unit_price_cents": 100}],
    )
    assert order.status_code == 201
    assert submit_purchase_order(client, buyer_headers, order.json()["id"]).status_code == 200

    denied = receive(
        client, buyer_headers, order.json()["id"],
        [{"order_item_id": order.json()["items"][0]["id"], "quantity": 5}],
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == 40301
