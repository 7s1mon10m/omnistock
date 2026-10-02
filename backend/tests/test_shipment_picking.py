"""Pick-list construction and scan validation.

Two things carry the weight here:

* the pick order is sorted by **warehouse location**, which is what turns a list
  of SKUs into a walking route;
* a scan that does not match the list is refused, and the refusal is recorded —
  you find out at the shelf, not from the customer's complaint.
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
    pick,
    set_stock_location,
    stock_of,
    uniq,
)


@pytest.fixture()
def pickable(client, owner_headers, catalog):
    """Two SKUs deliberately filed in *reverse* alphabetical order.

    SKU-A sits in B-01 and SKU-B sits in A-01, so a pick list sorted by SKU code
    and one sorted by location produce visibly different routes.
    """
    tag = uniq("PK")
    spu = create_spu(client, owner_headers, f"SPU-{tag}", "拣货测试商品")
    sku_a = create_sku(
        client, owner_headers, spu["id"], sku_code=f"SKU-A-{tag}", barcode=f"8{tag}1", safety_qty=0
    )
    sku_b = create_sku(
        client, owner_headers, spu["id"], sku_code=f"SKU-B-{tag}", barcode=f"8{tag}2", safety_qty=0
    )

    warehouse_id = catalog["warehouse"]["id"]
    for sku in (sku_a, sku_b):
        adjust_stock(client, catalog["headers"], sku["id"], warehouse_id, 50, "备货")

    loc_a = create_location(client, owner_headers, warehouse_id, code=f"B-{tag}")
    loc_b = create_location(client, owner_headers, warehouse_id, code=f"A-{tag}")
    set_stock_location(client, owner_headers, sku_a["id"], warehouse_id, loc_a["id"])
    set_stock_location(client, owner_headers, sku_b["id"], warehouse_id, loc_b["id"])

    channel = create_channel(client, owner_headers, code=uniq("PKCH"))
    code_a, code_b = uniq("PA"), uniq("PB")
    create_mapping(client, owner_headers, channel["id"], code_a, sku_a["id"])
    create_mapping(client, owner_headers, channel["id"], code_b, sku_b["id"])

    return {
        "sku_a": sku_a,
        "sku_b": sku_b,
        "loc_a": loc_a,
        "loc_b": loc_b,
        "channel": channel,
        "code_a": code_a,
        "code_b": code_b,
        "warehouse": catalog["warehouse"],
        "catalog": catalog,
    }


def _reserve(client, headers, pickable, order_no: str) -> int:
    import_orders(
        client,
        headers,
        [
            order_payload(
                pickable["channel"]["code"],
                order_no,
                [
                    {"channel_product_code": pickable["code_a"], "quantity": 3},
                    {"channel_product_code": pickable["code_b"], "quantity": 2},
                ],
            )
        ],
    )
    return first_order_id(client, headers, order_no)


# ------------------------------------------------------------------ pick list
def test_pick_list_is_sorted_by_location_not_by_sku(client, owner_headers, pickable):
    order_id = _reserve(client, owner_headers, pickable, "PK-SORT-1")
    shipment = create_shipment(client, owner_headers, order_id)
    assert shipment.status_code == 201, shipment.text
    body = shipment.json()

    codes = [(item["line_no"], item["sku_code"], item["location_code"]) for item in body["items"]]
    assert [row[2] for row in codes] == [pickable["loc_b"]["code"], pickable["loc_a"]["code"]]
    assert body["shipment_no"].startswith("SHP")
    assert body["total_quantity"] == 5
    assert body["picked_quantity"] == 0


def test_a_sku_without_a_location_is_picked_last(client, owner_headers, pickable):
    set_stock_location(
        client, owner_headers, pickable["sku_a"]["id"], pickable["warehouse"]["id"], None
    )
    order_id = _reserve(client, owner_headers, pickable, "PK-SORT-2")
    body = get_shipment(
        client, owner_headers, create_shipment(client, owner_headers, order_id).json()["id"]
    )

    locations = [item["location_code"] for item in body["items"]]
    assert locations[-1] == ""  # 未维护库位的排在最后


def test_creating_a_shipment_moves_the_order_into_picking(client, owner_headers, pickable):
    order_id = _reserve(client, owner_headers, pickable, "PK-STATE-1")
    assert client.get(f"{API}/orders/{order_id}", headers=owner_headers).json()["status"] == "reserved"

    create_shipment(client, owner_headers, order_id)
    assert client.get(f"{API}/orders/{order_id}", headers=owner_headers).json()["status"] == "picking"


def test_a_second_shipment_for_the_same_order_is_refused(client, owner_headers, pickable):
    order_id = _reserve(client, owner_headers, pickable, "PK-DUP-1")
    first = create_shipment(client, owner_headers, order_id).json()

    again = create_shipment(client, owner_headers, order_id)
    assert again.status_code == 409
    assert again.json()["code"] == 40931
    assert again.json()["detail"]["shipment_id"] == first["id"]


def test_an_unpaid_order_cannot_be_shipped(client, owner_headers, pickable, monkeypatch):
    """未付款（未占用）的订单不能开拣货单。"""
    monkeypatch.setattr(settings, "ORDER_IMPORT_ASSUME_PAID", False)
    import_orders(
        client,
        owner_headers,
        [
            order_payload(
                pickable["channel"]["code"],
                "PK-UNPAID-1",
                [{"channel_product_code": pickable["code_a"], "quantity": 1}],
            )
        ],
    )
    order_id = first_order_id(client, owner_headers, "PK-UNPAID-1")
    order = client.get(f"{API}/orders/{order_id}", headers=owner_headers).json()
    assert order["status"] == "pending_payment"
    assert order["reservations"] == []

    response = create_shipment(client, owner_headers, order_id)
    assert response.status_code == 409
    assert response.json()["code"] == 40937


def test_a_shipment_for_an_unknown_order_returns_404(client, owner_headers):
    response = create_shipment(client, owner_headers, 987654)
    assert response.status_code == 404
    assert response.json()["code"] == 40423


def test_a_bundle_order_yields_component_pick_lines(client, owner_headers, catalog):
    """套装订单的拣货单指向实际要拿的子 SKU。"""
    tag = uniq("PB")
    comp_spu = create_spu(client, owner_headers, f"SPU-C-{tag}", "子商品")
    component = create_sku(
        client, owner_headers, comp_spu["id"], sku_code=f"COMP-{tag}", barcode=f"7{tag}", safety_qty=0
    )
    adjust_stock(
        client, catalog["headers"], component["id"], catalog["warehouse"]["id"], 30, "备货"
    )

    set_spu = create_spu(client, owner_headers, f"SPU-S-{tag}", "套装", type_="bundle")
    bundle = create_sku(
        client, owner_headers, set_spu["id"], sku_code=f"SET-{tag}", safety_qty=0
    )
    client.put(
        f"{API}/bundles/{bundle['id']}/components",
        json={"components": [{"component_sku_id": component["id"], "quantity": 2}]},
        headers=owner_headers,
    )

    channel = create_channel(client, owner_headers, code=uniq("PBCH"))
    map_code = uniq("PC")
    create_mapping(client, owner_headers, channel["id"], map_code, bundle["id"])

    import_orders(
        client,
        owner_headers,
        [
            order_payload(
                channel["code"], "PK-BUNDLE-1", [{"channel_product_code": map_code, "quantity": 3}]
            )
        ],
    )
    order_id = first_order_id(client, owner_headers, "PK-BUNDLE-1")
    body = create_shipment(client, owner_headers, order_id).json()

    # 3 套 × 每套 2 件 = 拣 6 件子商品，而不是 3 件套装
    assert len(body["items"]) == 1
    assert body["items"][0]["sku_id"] == component["id"]
    assert body["items"][0]["quantity"] == 6
    assert body["items"][0]["is_bundle_component"] is True


# --------------------------------------------------------------------- scans
def test_scanning_the_right_barcode_advances_the_line(client, owner_headers, pickable):
    order_id = _reserve(client, owner_headers, pickable, "PK-SCAN-1")
    shipment = create_shipment(client, owner_headers, order_id).json()

    response = pick(client, owner_headers, shipment["id"], pickable["sku_b"]["barcode"], 2)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accepted"] is True
    assert body["progress"] == "2/5"
    assert body["shipment_status"] == "picking"


def test_scanning_a_sku_that_is_not_on_the_list_is_refused(client, owner_headers, pickable, catalog):
    """扫到别的 SKU —— 当场拦截，并留下记录。"""
    extra_spu = create_spu(client, owner_headers, uniq("SPU-X"), "不在单上的商品")
    stranger = create_sku(
        client, owner_headers, extra_spu["id"], sku_code=uniq("STRANGER"), barcode=uniq("6"), safety_qty=0
    )
    assert stranger

    order_id = _reserve(client, owner_headers, pickable, "PK-SCAN-2")
    shipment = create_shipment(client, owner_headers, order_id).json()

    response = pick(client, owner_headers, shipment["id"], stranger["barcode"], 1)
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert body["result"] == "wrong_sku"
    assert "不在本单拣货清单" in body["message"]

    # The rejection is recorded, and nothing was picked.
    records = client.get(
        f"{API}/shipments/{shipment['id']}/pick-records", headers=owner_headers
    ).json()
    assert records["items"][0]["accepted"] is False
    assert records["items"][0]["result"] == "wrong_sku"
    assert get_shipment(client, owner_headers, shipment["id"])["picked_quantity"] == 0


def test_an_unknown_barcode_is_refused(client, owner_headers, pickable):
    order_id = _reserve(client, owner_headers, pickable, "PK-SCAN-3")
    shipment = create_shipment(client, owner_headers, order_id).json()

    body = pick(client, owner_headers, shipment["id"], "000000000000", 1).json()
    assert body["accepted"] is False
    assert body["result"] == "barcode_not_found"


def test_scanning_more_than_required_is_refused(client, owner_headers, pickable):
    order_id = _reserve(client, owner_headers, pickable, "PK-SCAN-4")
    shipment = create_shipment(client, owner_headers, order_id).json()

    over = pick(client, owner_headers, shipment["id"], pickable["sku_b"]["barcode"], 5).json()
    assert over["accepted"] is False
    assert over["result"] == "over_quantity"
    assert "只剩 2 件未拣" in over["message"]


def test_scanning_an_already_complete_line_is_refused(client, owner_headers, pickable):
    order_id = _reserve(client, owner_headers, pickable, "PK-SCAN-5")
    shipment = create_shipment(client, owner_headers, order_id).json()

    assert pick(client, owner_headers, shipment["id"], pickable["sku_b"]["barcode"], 2).json()[
        "accepted"
    ]
    again = pick(client, owner_headers, shipment["id"], pickable["sku_b"]["barcode"], 1).json()
    assert again["accepted"] is False
    assert again["result"] == "over_quantity"
    assert "已经拣够" in again["message"]


def test_scanning_everything_marks_the_shipment_picked(client, owner_headers, pickable):
    order_id = _reserve(client, owner_headers, pickable, "PK-SCAN-6")
    shipment = create_shipment(client, owner_headers, order_id).json()

    pick(client, owner_headers, shipment["id"], pickable["sku_a"]["barcode"], 3)
    final = pick(client, owner_headers, shipment["id"], pickable["sku_b"]["barcode"], 2)
    assert final.json()["shipment_status"] == "picked"
    assert final.json()["progress"] == "5/5"


def test_an_extra_barcode_also_works(client, owner_headers, pickable):
    """一个 SKU 可以有多个条码，拣货时任何一个都认。"""
    sku = pickable["sku_a"]
    extra_code = uniq("9")
    client.post(
        f"{API}/skus/{sku['id']}/barcodes",
        json={"barcode": extra_code, "remark": "备用条码"},
        headers=owner_headers,
    )

    order_id = _reserve(client, owner_headers, pickable, "PK-SCAN-7")
    shipment = create_shipment(client, owner_headers, order_id).json()
    assert pick(client, owner_headers, shipment["id"], extra_code, 3).json()["accepted"] is True

    stock = stock_of(
        client, owner_headers, sku["id"], pickable["warehouse"]["id"]
    )
    assert stock["reserved_qty"] == 3


def test_manual_pick_works_without_a_barcode(client, owner_headers, pickable):
    order_id = _reserve(client, owner_headers, pickable, "PK-MANUAL-1")
    shipment = create_shipment(client, owner_headers, order_id).json()
    first = shipment["items"][0]

    response = client.post(
        f"{API}/shipments/{shipment['id']}/pick-manual",
        json={"shipment_item_id": first["id"], "quantity": first["quantity"]},
        headers=owner_headers,
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True

    over = client.post(
        f"{API}/shipments/{shipment['id']}/pick-manual",
        json={"shipment_item_id": first["id"], "quantity": 1},
        headers=owner_headers,
    )
    assert over.status_code == 409
    assert over.json()["code"] == 40933


def test_first_scan_implicitly_claims_the_job(client, owner_headers, pickable):
    order_id = _reserve(client, owner_headers, pickable, "PK-CLAIM-1")
    shipment = create_shipment(client, owner_headers, order_id).json()
    assert shipment["status"] == "pending"

    pick(client, owner_headers, shipment["id"], pickable["sku_b"]["barcode"], 1)
    after = get_shipment(client, owner_headers, shipment["id"])
    assert after["status"] == "picking"
    assert after["picker_id"] is not None


def test_a_shipment_for_an_unknown_order_returns_404(client, owner_headers):
    response = create_shipment(client, owner_headers, 987654)
    assert response.status_code == 404
    assert response.json()["code"] == 40423
