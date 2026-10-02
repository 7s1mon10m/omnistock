"""退货质检四路分流。

这个模块唯一要证明的事：**四种质检结论分别落到四个不同的地方**，而且
次品和维修品永远不会出现在可售库存里。

混成一条「退货入库」是这个模块最容易犯的错 —— 那样做的话，一批退回来的
次品会立刻变成「可以卖的货」，后面的缺货判断、补货建议全都跟着错。
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from conftest import (
    API,
    create_return,
    adjust_stock,
    create_channel,
    create_mapping,
    create_sku,
    create_spu,
    create_warehouse,
    get_return,
    import_orders,
    inbound_return,
    inspect_return,
    inventory_row_or_zero,
    order_payload,
    pack,
    pick,
    ship,
    uniq,
)


@pytest.fixture()
def sold(client, owner_headers, monkeypatch):
    """一笔真正发货出去的订单：10 件已售，仓库里还剩 90。

    退货校验的基准是「已售 - 已退」，所以必须走完整的发货流程，光有订单不够。
    """
    tag = uniq("RET")
    warehouse = create_warehouse(client, owner_headers, name=f"退货仓{tag}", code=f"WH-{tag}")
    # 订单默认落到 DEFAULT_WAREHOUSE_CODE，必须指到这个仓，否则占用会落到别处
    monkeypatch.setattr(settings, "DEFAULT_WAREHOUSE_CODE", warehouse["code"])
    spu = create_spu(client, owner_headers, f"SPU-{tag}", "退货商品")
    sku = create_sku(
        client,
        owner_headers,
        spu["id"],
        sku_code=f"SKU-{tag}",
        barcode=f"BC{tag}",
        safety_qty=0,
    )
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 100, "备货")

    channel = create_channel(client, owner_headers, name=f"退货渠道{tag}")
    create_mapping(client, owner_headers, channel["id"], f"P{tag}", sku["id"])

    import_orders(
        client,
        owner_headers,
        [
            order_payload(
                channel["code"],
                f"RET-{tag}",
                [{"channel_product_code": f"P{tag}", "quantity": 10}],
            )
        ],
    )
    order = client.get(
        f"{API}/orders?keyword=RET-{tag}", headers=owner_headers
    ).json()["items"][0]

    shipment = client.post(
        f"{API}/shipments", json={"order_id": order["id"]}, headers=owner_headers
    ).json()
    pick(client, owner_headers, shipment["id"], sku["barcode"], 10)
    pack(client, owner_headers, shipment["id"])
    ship(client, owner_headers, shipment["id"])

    return {
        "warehouse": warehouse,
        "spu": spu,
        "sku": sku,
        "order": order,
        "channel": channel,
        "headers": owner_headers,
        "tag": tag,
    }


def make_return(client, headers, fixture, quantity: int, **extra):
    from conftest import create_return

    response = create_return(
        client,
        headers,
        fixture["warehouse"]["id"],
        [{"sku_id": fixture["sku"]["id"], "quantity": quantity}],
        order_id=fixture["order"]["id"],
        channel_order_no=fixture["order"]["channel_order_no"],
        **extra,
    )
    assert response.status_code == 201, response.text
    return response.json()


# ------------------------------------------------------------------ 创建校验
def test_a_return_can_be_filed_against_its_original_order(client, owner_headers, sold):
    body = make_return(client, owner_headers, sold, 4)
    assert body["status"] == "pending"
    assert body["total_quantity"] == 4
    assert body["items"][0]["sold_qty"] == 10, "销量快照必须落在行上，供后续校验"


def test_returning_more_than_sold_is_refused(client, owner_headers, sold):
    from conftest import create_return

    response = create_return(
        client,
        owner_headers,
        sold["warehouse"]["id"],
        [{"sku_id": sold["sku"]["id"], "quantity": 11}],
        order_id=sold["order"]["id"],
    )
    assert response.status_code == 409
    assert response.json()["code"] == 40980, "已售 10 件，不能退 11 件"


def test_a_second_return_respects_what_was_already_returned(client, owner_headers, sold):
    """退两次，两次加起来不能超过已售。"""
    from conftest import create_return

    make_return(client, owner_headers, sold, 6)
    first_id = client.get(
        f"{API}/return-orders?keyword={sold['order']['channel_order_no']}", headers=owner_headers
    ).json()["items"][0]["id"]
    inspect_return(
        client,
        owner_headers,
        first_id,
        [
            {
                "return_item_id": client.get(
                    f"{API}/return-orders/{first_id}", headers=owner_headers
                ).json()["items"][0]["id"],
                "disposition": "resellable",
                "resellable_qty": 6,
            }
        ],
    )
    inbound_return(client, owner_headers, first_id)

    response = create_return(
        client,
        owner_headers,
        sold["warehouse"]["id"],
        [{"sku_id": sold["sku"]["id"], "quantity": 5}],
        order_id=sold["order"]["id"],
    )
    assert response.status_code == 409
    assert response.json()["code"] == 40980, "已退 6 件，剩余可退 4 件"


def test_a_return_without_any_order_reference_is_refused(client, owner_headers, sold):
    from conftest import create_return

    response = create_return(
        client,
        owner_headers,
        sold["warehouse"]["id"],
        [{"sku_id": sold["sku"]["id"], "quantity": 1}],
    )
    assert response.status_code == 400


# ------------------------------------------------------------------ 质检分流
def test_the_four_dispositions_land_in_four_different_places(client, owner_headers, sold):
    """退 6 件：3 可再售 / 1 次品 / 1 维修 / 1 报损。"""
    body = make_return(client, owner_headers, sold, 6)
    rid = body["id"]
    item_id = body["items"][0]["id"]

    before = inventory_row_or_zero(
        client, owner_headers, sold["sku"]["id"], sold["warehouse"]["id"]
    )

    inspect_return(
        client,
        owner_headers,
        rid,
        [
            {
                "return_item_id": item_id,
                "disposition": "resellable",
                "resellable_qty": 3,
                "defective_qty": 1,
                "repair_qty": 1,
                "scrap_qty": 1,
            }
        ],
    )

    # 质检只记结论，不动库存 —— 这是分流能反悔的前提
    mid = inventory_row_or_zero(
        client, owner_headers, sold["sku"]["id"], sold["warehouse"]["id"]
    )
    assert mid["on_hand_qty"] == before["on_hand_qty"], "质检阶段绝不能改库存"

    inbound_return(client, owner_headers, rid)

    after = inventory_row_or_zero(
        client, owner_headers, sold["sku"]["id"], sold["warehouse"]["id"]
    )
    assert after["on_hand_qty"] - before["on_hand_qty"] == 3, "只有可再售的 3 件回到可售"
    assert after["defective_qty"] - before["defective_qty"] == 1
    assert after["repair_qty"] - before["repair_qty"] == 1
    # 报损的那件从账面消失：它既不是可售也不是次品
    assert after["available_qty"] - before["available_qty"] == 3


def test_defectives_never_enter_sellable_stock(client, owner_headers, sold):
    """整批都是次品时，可售库存一点都不许变。"""
    body = make_return(client, owner_headers, sold, 5)
    rid, item_id = body["id"], body["items"][0]["id"]

    before = inventory_row_or_zero(
        client, owner_headers, sold["sku"]["id"], sold["warehouse"]["id"]
    )

    inspect_return(
        client,
        owner_headers,
        rid,
        [
            {
                "return_item_id": item_id,
                "disposition": "defective",
                "resellable_qty": 0,
                "defective_qty": 5,
            }
        ],
    )
    inbound_return(client, owner_headers, rid)

    after = inventory_row_or_zero(
        client, owner_headers, sold["sku"]["id"], sold["warehouse"]["id"]
    )
    assert after["on_hand_qty"] == before["on_hand_qty"]
    assert after["defective_qty"] == before["defective_qty"] + 5
    assert after["available_qty"] == before["available_qty"], "次品绝不能变成能卖的货"


def test_the_split_total_must_match_the_returned_quantity(client, owner_headers, sold):
    body = make_return(client, owner_headers, sold, 5)
    response = inspect_return(
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
    assert response.status_code == 400
    assert response.json()["code"] == 40060


def test_every_line_must_be_inspected_before_inbound(client, owner_headers, sold):
    body = make_return(client, owner_headers, sold, 3)
    response = inbound_return(client, owner_headers, body["id"])
    assert response.status_code == 409
    assert response.json()["code"] == 40982, "还没质检不能入库"


# ------------------------------------------------------------------ 状态机
def test_inbound_twice_is_refused(client, owner_headers, sold):
    body = make_return(client, owner_headers, sold, 2)
    rid, item_id = body["id"], body["items"][0]["id"]
    inspect_return(
        client,
        owner_headers,
        rid,
        [
            {
                "return_item_id": item_id,
                "disposition": "resellable",
                "resellable_qty": 2,
            }
        ],
    )
    assert inbound_return(client, owner_headers, rid).status_code == 200
    again = inbound_return(client, owner_headers, rid)
    assert again.status_code == 409
    assert again.json()["code"] == 40982


def test_a_cancelled_return_cannot_be_inbound(client, owner_headers, sold):
    body = make_return(client, owner_headers, sold, 2)
    rid = body["id"]
    cancelled = client.post(
        f"{API}/return-orders/{rid}/cancel", json={"reason": "客户撤销"}, headers=owner_headers
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert inbound_return(client, owner_headers, rid).status_code == 409


# ------------------------------------------------------------------ 可追溯
def test_every_ledger_row_is_traceable_by_return_order_id(client, owner_headers, sold):
    body = make_return(client, owner_headers, sold, 4)
    rid, item_id = body["id"], body["items"][0]["id"]
    inspect_return(
        client,
        owner_headers,
        rid,
        [
            {
                "return_item_id": item_id,
                "disposition": "resellable",
                "resellable_qty": 2,
                "defective_qty": 1,
                "repair_qty": 1,
            }
        ],
    )
    inbound_return(client, owner_headers, rid)

    ledger = client.get(
        f"{API}/inventory/ledger?sku_id={sold['sku']['id']}&page_size=100", headers=owner_headers
    ).json()["items"]
    mine = [row for row in ledger if row["ref_type"] == "return_order"]
    assert {row["type"] for row in mine} == {"return_inbound", "return_defective", "return_repair"}
    # 每一条都能反查到这张退货单
    assert {row["ref_id"] for row in mine} == {rid}


def test_only_warehouse_staff_may_inbound(client, owner_headers, sold, operator_headers):
    body = make_return(client, owner_headers, sold, 1)
    # 运营能受理退货，但不能把货入到库里
    assert inbound_return(client, operator_headers, body["id"]).status_code == 403
