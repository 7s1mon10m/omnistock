"""Packing gates, outbound deduction, state machine and cancellation.

The rule under test throughout: stock never leaves the shelf until the parcel is
packed, and when it does leave, on-hand *and* the reservation drop together.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from conftest import (
    API,
    adjust_stock,
    create_channel,
    create_location,
    create_mapping,
    create_shipment,
    create_sku,
    create_spu,
    first_order_id,
    get_shipment,
    import_orders,
    order_payload,
    pack,
    pick,
    pick_everything,
    set_stock_location,
    ship,
    stock_of,
    uniq,
)

SHIPMENT_ITEM = "shipment_item_id"


@pytest.fixture()
def ready(client, owner_headers, catalog):
    """One SKU, one reserved order, exposed as small helper functions."""
    tag = uniq("FL")
    spu = create_spu(client, owner_headers, f"SPU-{tag}", "发货流程商品")
    sku = create_sku(
        client, owner_headers, spu["id"], sku_code=f"SKU-{tag}", barcode=f"5{tag}", safety_qty=0
    )
    warehouse_id = catalog["warehouse"]["id"]
    adjust_stock(client, catalog["headers"], sku["id"], warehouse_id, 40, "备货")
    location = create_location(client, owner_headers, warehouse_id, code=f"A-{tag}")
    set_stock_location(client, owner_headers, sku["id"], warehouse_id, location["id"])

    channel = create_channel(client, owner_headers, code=uniq("FLCH"))
    map_code = uniq("PF")
    create_mapping(client, owner_headers, channel["id"], map_code, sku["id"])

    def reserve(order_no: str, quantity: int = 5) -> int:
        import_orders(
            client,
            owner_headers,
            [
                order_payload(
                    channel["code"], order_no, [{"channel_product_code": map_code, "quantity": quantity}]
                )
            ],
        )
        return first_order_id(client, owner_headers, order_no)

    def open_shipment(order_no: str, quantity: int = 5) -> dict:
        order_id = reserve(order_no, quantity)
        response = create_shipment(client, owner_headers, order_id)
        assert response.status_code == 201, response.text
        return response.json()

    return {
        "sku": sku,
        "location": location,
        "warehouse": catalog["warehouse"],
        "catalog": catalog,
        "reserve": reserve,
        "open_shipment": open_shipment,
    }


# ------------------------------------------------------------------ the gates
def test_packing_before_picking_is_complete_is_refused(client, owner_headers, ready):
    shipment = ready["open_shipment"]("FL-GATE-1")
    pick(client, owner_headers, shipment["id"], ready["sku"]["barcode"], 2)

    response = pack(client, owner_headers, shipment["id"])
    assert response.status_code == 409
    assert response.json()["code"] == 40934
    assert response.json()["detail"] == {"picked": 2, "required": 5}


def test_shipping_before_packing_is_refused(client, owner_headers, ready):
    shipment = ready["open_shipment"]("FL-GATE-2")
    pick_everything(client, owner_headers, get_shipment(client, owner_headers, shipment["id"]))

    response = ship(client, owner_headers, shipment["id"])
    assert response.status_code == 409
    assert response.json()["code"] == 40935


def test_packing_before_every_line_is_picked_is_refused_by_default(client, owner_headers, ready):
    """默认不允许部分拣货发货。"""
    shipment = ready["open_shipment"]("FL-GATE-3")
    # 只扫满一个 5 件的行，其余 0
    assert settings.SHIPMENT_ALLOW_PARTIAL_PICK is False
    assert pack(client, owner_headers, shipment["id"]).json()["code"] == 40934


def test_partial_pick_can_be_allowed_by_configuration(client, owner_headers, ready, monkeypatch):
    """开启短拣后，按实际拣到的数量发货，剩余占用会被释放。"""
    monkeypatch.setattr(settings, "SHIPMENT_ALLOW_PARTIAL_PICK", True)
    shipment = ready["open_shipment"]("FL-GATE-4", quantity=5)
    pick(client, owner_headers, shipment["id"], ready["sku"]["barcode"], 3)

    assert pack(client, owner_headers, shipment["id"]).status_code == 200
    shipped = ship(client, owner_headers, shipment["id"])
    assert shipped.status_code == 200, shipped.text
    # 只出库了 3 件
    assert shipped.json()["outbound"][0]["quantity"] == 3

    stock = stock_of(client, owner_headers, ready["sku"]["id"], ready["warehouse"]["id"])
    assert stock["on_hand_qty"] == 37, "只应扣减实际拣到的 3 件"
    assert stock["reserved_qty"] == 0, "没发出去的那 2 件占用必须被释放"


def test_packing_with_nothing_picked_is_refused_even_when_partial_is_allowed(
    client, owner_headers, ready, monkeypatch
):
    monkeypatch.setattr(settings, "SHIPMENT_ALLOW_PARTIAL_PICK", True)
    shipment = ready["open_shipment"]("FL-GATE-5")

    response = pack(client, owner_headers, shipment["id"])
    assert response.status_code == 409
    assert response.json()["code"] == 40934
    assert "一件都没有拣" in response.json()["message"]


# ------------------------------------------------------------------- the flow
def test_the_full_flow_deducts_on_hand_and_clears_the_hold(client, owner_headers, ready):
    sku_id = ready["sku"]["id"]
    warehouse_id = ready["warehouse"]["id"]
    shipment = ready["open_shipment"]("FL-FLOW-1", quantity=5)

    before = stock_of(client, owner_headers, sku_id, warehouse_id)
    assert (before["on_hand_qty"], before["reserved_qty"]) == (40, 5)

    pick_everything(client, owner_headers, get_shipment(client, owner_headers, shipment["id"]))
    assert pack(client, owner_headers, shipment["id"], weight_g=750).status_code == 200

    response = ship(client, owner_headers, shipment["id"], carrier="顺丰", tracking_no="SF999")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["shipment"]["status"] == "shipped"
    assert body["shipment"]["tracking_no"] == "SF999"
    assert body["outbound"] == [
        {
            "sku_id": sku_id,
            "sku_code": ready["sku"]["sku_code"],
            "warehouse_code": ready["warehouse"]["code"],
            "quantity": 5,
        }
    ]

    after = stock_of(client, owner_headers, sku_id, warehouse_id)
    assert after["on_hand_qty"] == 35, "实际库存没有被扣减"
    assert after["reserved_qty"] == 0, "占用没有被释放"
    assert after["available_qty"] == 35

    order = client.get(
        f"{API}/orders/{body['shipment']['order_id']}", headers=owner_headers
    ).json()
    assert order["status"] == "shipped"
    assert order["reservations"] == []


def test_the_ledger_records_the_outbound(client, owner_headers, ready):
    shipment = ready["open_shipment"]("FL-LEDGER-1", quantity=4)
    pick_everything(client, owner_headers, get_shipment(client, owner_headers, shipment["id"]))
    pack(client, owner_headers, shipment["id"])
    ship(client, owner_headers, shipment["id"])

    ledger = client.get(
        f"{API}/inventory/ledger?sku_id={ready['sku']['id']}&page_size=200",
        headers=owner_headers,
    ).json()["items"]
    types = [row["type"] for row in ledger]
    assert "order_outbound" in types

    outbound = next(row for row in ledger if row["type"] == "order_outbound")
    assert outbound["qty_delta"] == -4
    assert outbound["on_hand_before"] == 40
    assert outbound["on_hand_after"] == 36
    assert outbound["reserved_before"] == 4
    assert outbound["reserved_after"] == 0
    # 前后值自洽
    assert outbound["on_hand_before"] + outbound["qty_delta"] == outbound["on_hand_after"]


def test_packing_stores_the_parcel_details(client, owner_headers, ready):
    shipment = ready["open_shipment"]("FL-PACK-1")
    pick_everything(client, owner_headers, get_shipment(client, owner_headers, shipment["id"]))

    body = pack(
        client, owner_headers, shipment["id"], package_count=2, weight_g=1500
    ).json()
    assert body["status"] == "packed"
    assert body["package_count"] == 2
    assert body["weight_g"] == 1500
    assert body["packed_at"] is not None
    assert body["packed_by_name"]


# ------------------------------------------------------------- state machine
def test_a_shipped_shipment_cannot_be_shipped_again(client, owner_headers, ready):
    shipment = ready["open_shipment"]("FL-SM-1")
    pick_everything(client, owner_headers, get_shipment(client, owner_headers, shipment["id"]))
    pack(client, owner_headers, shipment["id"])
    assert ship(client, owner_headers, shipment["id"]).status_code == 200

    again = ship(client, owner_headers, shipment["id"])
    assert again.status_code == 409
    assert again.json()["code"] == 40930

    # 库存只被扣了一次
    after = stock_of(client, owner_headers, ready["sku"]["id"], ready["warehouse"]["id"])
    assert after["on_hand_qty"] == 35


def test_a_shipped_shipment_cannot_be_cancelled(client, owner_headers, ready):
    shipment = ready["open_shipment"]("FL-SM-2")
    pick_everything(client, owner_headers, get_shipment(client, owner_headers, shipment["id"]))
    pack(client, owner_headers, shipment["id"])
    ship(client, owner_headers, shipment["id"])

    response = client.post(
        f"{API}/shipments/{shipment['id']}/cancel", json={"reason": "来不及了"}, headers=owner_headers
    )
    assert response.status_code == 409
    assert response.json()["code"] == 40930


def test_picking_after_shipping_is_refused(client, owner_headers, ready):
    shipment = ready["open_shipment"]("FL-SM-3")
    pick_everything(client, owner_headers, get_shipment(client, owner_headers, shipment["id"]))
    pack(client, owner_headers, shipment["id"])
    ship(client, owner_headers, shipment["id"])

    response = pick(client, owner_headers, shipment["id"], ready["sku"]["barcode"], 1)
    assert response.status_code == 409
    assert response.json()["code"] == 40930


def test_cancelling_releases_nothing_but_hands_the_order_back(client, owner_headers, ready):
    """取消发货单不等于取消订单 —— 占用仍然属于订单。"""
    shipment = ready["open_shipment"]("FL-CANCEL-1", quantity=5)
    pick(client, owner_headers, shipment["id"], ready["sku"]["barcode"], 2)

    response = client.post(
        f"{API}/shipments/{shipment['id']}/cancel",
        json={"reason": "客户要求改地址"},
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"

    stock = stock_of(client, owner_headers, ready["sku"]["id"], ready["warehouse"]["id"])
    assert stock["on_hand_qty"] == 40, "取消发货单不应影响实际库存"
    assert stock["reserved_qty"] == 5, "占用仍属于订单"

    order = client.get(
        f"{API}/orders/{response.json()['order_id']}", headers=owner_headers
    ).json()
    assert order["status"] == "reserved"


def test_a_cancelled_shipment_can_be_recreated(client, owner_headers, ready):
    first = ready["open_shipment"]("FL-REDO-1")
    client.post(f"{API}/shipments/{first['id']}/cancel", json={}, headers=owner_headers)

    order_id = first["order_id"]
    second = create_shipment(client, owner_headers, order_id)
    assert second.status_code == 201, second.text
    assert second.json()["id"] != first["id"]
    # 重新生成的拣货单从零开始
    assert second.json()["picked_quantity"] == 0
    assert second.json()["status"] == "pending"


# ------------------------------------------------------------------- bundles
def test_a_bundle_shipment_deducts_the_components(client, owner_headers, catalog):
    tag = uniq("BS")
    comp_spu = create_spu(client, owner_headers, f"SPU-CC-{tag}", "套装配件")
    component = create_sku(
        client, owner_headers, comp_spu["id"], sku_code=f"CMP-{tag}", barcode=f"4{tag}", safety_qty=0
    )
    warehouse_id = catalog["warehouse"]["id"]
    adjust_stock(client, catalog["headers"], component["id"], warehouse_id, 20, "备货")
    create_location(client, owner_headers, warehouse_id, code=f"C-{tag}")

    set_spu = create_spu(client, owner_headers, f"SPU-SS-{tag}", "套装", type_="bundle")
    bundle = create_sku(client, owner_headers, set_spu["id"], sku_code=f"SET-{tag}", safety_qty=0)
    client.put(
        f"{API}/bundles/{bundle['id']}/components",
        json={"components": [{"component_sku_id": component["id"], "quantity": 2}]},
        headers=owner_headers,
    )

    channel = create_channel(client, owner_headers, code=uniq("BSCH"))
    map_code = uniq("PS")
    create_mapping(client, owner_headers, channel["id"], map_code, bundle["id"])
    import_orders(
        client,
        owner_headers,
        [
            order_payload(
                channel["code"], "FL-BUNDLE-1", [{"channel_product_code": map_code, "quantity": 3}]
            )
        ],
    )
    order_id = first_order_id(client, owner_headers, "FL-BUNDLE-1")

    shipment = create_shipment(client, owner_headers, order_id).json()
    assert shipment["items"][0]["quantity"] == 6  # 3 套 × 每套 2 件

    pick_everything(client, owner_headers, get_shipment(client, owner_headers, shipment["id"]))
    pack(client, owner_headers, shipment["id"])
    shipped = ship(client, owner_headers, shipment["id"])
    assert shipped.status_code == 200, shipped.text

    stock = stock_of(client, owner_headers, component["id"], warehouse_id)
    assert stock["on_hand_qty"] == 14, "套装出库应按子件扣减实际库存"
    assert stock["reserved_qty"] == 0

    # 套装 SKU 自己始终没有库存
    bundle_rows = client.get(
        f"{API}/inventory?sku_id={bundle['id']}", headers=owner_headers
    ).json()["items"]
    assert all(row["on_hand_qty"] == 0 for row in bundle_rows)


def test_the_customer_paid_for_the_bundle_not_the_components(client, owner_headers, catalog):
    """订单行仍是套装（客户买的东西），拣货行才是子件。"""
    tag = uniq("BI")
    comp_spu = create_spu(client, owner_headers, f"SPU-CI-{tag}", "配件")
    component = create_sku(
        client, owner_headers, comp_spu["id"], sku_code=f"C-{tag}", barcode=f"3{tag}", safety_qty=0
    )
    warehouse_id = catalog["warehouse"]["id"]
    adjust_stock(client, catalog["headers"], component["id"], warehouse_id, 10, "备货")

    set_spu = create_spu(client, owner_headers, f"SPU-SI-{tag}", "套装", type_="bundle")
    bundle = create_sku(client, owner_headers, set_spu["id"], sku_code=f"S-{tag}", safety_qty=0)
    client.put(
        f"{API}/bundles/{bundle['id']}/components",
        json={"components": [{"component_sku_id": component["id"], "quantity": 1}]},
        headers=owner_headers,
    )
    channel = create_channel(client, owner_headers, code=uniq("BICH"))
    map_code = uniq("PI")
    create_mapping(client, owner_headers, channel["id"], map_code, bundle["id"])
    import_orders(
        client,
        owner_headers,
        [
            order_payload(
                channel["code"], "FL-BUNDLE-2", [{"channel_product_code": map_code, "quantity": 2}]
            )
        ],
    )
    order_id = first_order_id(client, owner_headers, "FL-BUNDLE-2")

    order = client.get(f"{API}/orders/{order_id}", headers=owner_headers).json()
    assert order["items"][0]["sku_id"] == bundle["id"]
    assert order["items"][0]["is_bundle"] is True

    shipment = create_shipment(client, owner_headers, order_id).json()
    assert shipment["items"][0]["sku_id"] == component["id"]
    assert shipment["items"][0]["is_bundle_component"] is True


# ------------------------------------------------------------------ read views
def test_the_shipment_list_can_be_filtered(client, owner_headers, ready):
    shipment = ready["open_shipment"]("FL-LIST-1")

    by_status = client.get(
        f"{API}/shipments?status=pending&page_size=200", headers=owner_headers
    ).json()
    assert any(row["id"] == shipment["id"] for row in by_status["items"])

    by_keyword = client.get(
        f"{API}/shipments?keyword={shipment['shipment_no']}", headers=owner_headers
    ).json()
    assert by_keyword["total"] == 1
    assert by_keyword["items"][0]["order_no"] == shipment["order_no"]


def test_an_unknown_shipment_returns_404(client, owner_headers):
    assert client.get(f"{API}/shipments/987654", headers=owner_headers).json()["code"] == 40440
    assert (
        client.post(f"{API}/shipments/987654/pack", json={}, headers=owner_headers).json()["code"]
        == 40440
    )


def test_the_buyer_persona_cannot_pick(client, owner_headers, buyer_headers, ready):
    shipment = ready["open_shipment"]("FL-RBAC-1")

    assert client.get(f"{API}/shipments", headers=buyer_headers).status_code == 200
    denied = pick(client, buyer_headers, shipment["id"], ready["sku"]["barcode"], 1)
    assert denied.status_code == 403
    assert denied.json()["code"] == 40301


def test_the_warehouse_persona_can_run_the_whole_flow(
    client, owner_headers, warehouse_headers, ready
):
    """仓管是真正干活的人：领取、拣货、复核、出库都该由他完成。"""
    shipment = ready["open_shipment"]("FL-RBAC-2", quantity=2)

    assert (
        client.post(
            f"{API}/shipments/{shipment['id']}/claim", json={}, headers=warehouse_headers
        ).status_code
        == 200
    )
    assert pick(client, warehouse_headers, shipment["id"], ready["sku"]["barcode"], 2).json()[
        "accepted"
    ]
    assert pack(client, warehouse_headers, shipment["id"]).status_code == 200
    assert ship(client, warehouse_headers, shipment["id"]).status_code == 200

    body = get_shipment(client, owner_headers, shipment["id"])
    assert body["status"] == "shipped"
    assert body["picker_name"]
