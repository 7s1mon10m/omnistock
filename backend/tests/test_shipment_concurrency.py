"""并发与幂等：两张仓库平板、一次重复请求，都不能把货发两遍。

Shipping is the one irreversible step in the whole system — once a parcel leaves,
you cannot "undo" it by editing a number.  So the guards here are deliberately
database-level rather than service-level.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import (
    API,
    adjust_stock,
    create_channel,
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
    ship,
    stock_of,
    uniq,
)


@pytest.fixture()
def once(client, owner_headers, catalog):
    tag = uniq("CC")
    spu = create_spu(client, owner_headers, f"SPU-{tag}", "并发测试商品")
    sku = create_sku(
        client, owner_headers, spu["id"], sku_code=f"SKU-{tag}", barcode=f"2{tag}", safety_qty=0
    )
    warehouse_id = catalog["warehouse"]["id"]
    adjust_stock(client, catalog["headers"], sku["id"], warehouse_id, 100, "备货")

    channel = create_channel(client, owner_headers, code=uniq("CCH"))
    map_code = uniq("PC")
    create_mapping(client, owner_headers, channel["id"], map_code, sku["id"])

    def reserve(order_no: str, quantity: int = 6) -> int:
        import_orders(
            client,
            owner_headers,
            [
                order_payload(
                    channel["code"],
                    order_no,
                    [{"channel_product_code": map_code, "quantity": quantity}],
                )
            ],
        )
        return first_order_id(client, owner_headers, order_no)

    return {"sku": sku, "warehouse": catalog["warehouse"], "reserve": reserve}


def test_concurrent_shipment_creation_makes_only_one(client, owner_headers, once):
    """两台平板同时点「生成拣货单」，只能生成一张。"""
    order_id = once["reserve"]("CC-CREATE-1")

    def attempt(_: int) -> int:
        try:
            return create_shipment(client, owner_headers, order_id).status_code
        except Exception:  # pragma: no cover - a lost race may surface differently
            return 0

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(attempt, range(4)))

    created = [code for code in statuses if code == 201]
    assert len(created) == 1, f"并发创建了多张发货单：{statuses}"

    listed = client.get(
        f"{API}/shipments?page_size=200", headers=owner_headers
    ).json()["items"]
    mine = [row for row in listed if row["order_no"] == f"SO{order_id:08d}"]
    assert len(mine) == 1


def test_a_cancelled_shipment_frees_the_order_for_a_new_one(client, owner_headers, once):
    """部分唯一索引只挡「进行中」的发货单，取消后可以重开。"""
    order_id = once["reserve"]("CC-CREATE-2")
    first = create_shipment(client, owner_headers, order_id).json()

    client.post(f"{API}/shipments/{first['id']}/cancel", json={}, headers=owner_headers)
    second = create_shipment(client, owner_headers, order_id)
    assert second.status_code == 201, second.text

    # 但现在这一张又挡着了
    assert create_shipment(client, owner_headers, order_id).json()["code"] == 40931


def test_shipping_twice_never_deducts_twice(client, owner_headers, once):
    """重复调用发货接口，库存只能被扣一次。"""
    order_id = once["reserve"]("CC-SHIP-1", quantity=4)
    shipment = create_shipment(client, owner_headers, order_id).json()
    pick(client, owner_headers, shipment["id"], once["sku"]["barcode"], 4)
    pack(client, owner_headers, shipment["id"])

    first = ship(client, owner_headers, shipment["id"])
    assert first.status_code == 200, first.text
    second = ship(client, owner_headers, shipment["id"])
    assert second.status_code == 409

    stock = stock_of(client, owner_headers, once["sku"]["id"], once["warehouse"]["id"])
    assert stock["on_hand_qty"] == 96, "发货被扣了两次"
    assert stock["reserved_qty"] == 0

    ledger = client.get(
        f"{API}/inventory/ledger?sku_id={once['sku']['id']}&page_size=200",
        headers=owner_headers,
    ).json()["items"]
    outbound = [row for row in ledger if row["type"] == "order_outbound"]
    assert len(outbound) == 1


def test_concurrent_shipping_deducts_once(client, owner_headers, once):
    """两个请求同时点「出库发货」，库存也只能扣一次。"""
    order_id = once["reserve"]("CC-SHIP-2", quantity=5)
    shipment = create_shipment(client, owner_headers, order_id).json()
    pick(client, owner_headers, shipment["id"], once["sku"]["barcode"], 5)
    pack(client, owner_headers, shipment["id"])

    def attempt(_: int) -> int:
        try:
            return ship(client, owner_headers, shipment["id"]).status_code
        except Exception:  # pragma: no cover - a lost race may surface differently
            return 0

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(attempt, range(4)))

    assert statuses.count(200) <= 1, f"并发重复出库：{statuses}"

    stock = stock_of(client, owner_headers, once["sku"]["id"], once["warehouse"]["id"])
    assert stock["on_hand_qty"] == 95
    assert stock["reserved_qty"] == 0
    assert stock["on_hand_qty"] >= 0

    ledger = client.get(
        f"{API}/inventory/ledger?sku_id={once['sku']['id']}&page_size=200",
        headers=owner_headers,
    ).json()["items"]
    assert len([row for row in ledger if row["type"] == "order_outbound"]) == 1


def test_concurrent_scans_cannot_over_pick(client, owner_headers, once):
    """多人同时扫同一条，已拣数量不能超过应拣数量。"""
    order_id = once["reserve"]("CC-SCAN-1", quantity=3)
    shipment = create_shipment(client, owner_headers, order_id).json()

    def attempt(_: int) -> str:
        try:
            return pick(
                client, owner_headers, shipment["id"], once["sku"]["barcode"], 1
            ).json().get("result", "")
        except Exception:  # pragma: no cover
            return "error"

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))

    accepted = results.count("ok")
    assert accepted <= 3, f"超拣了：{results}"

    body = get_shipment(client, owner_headers, shipment["id"])
    assert body["picked_quantity"] <= body["total_quantity"]
    assert body["picked_quantity"] == accepted


def test_a_shipped_order_cannot_be_cancelled_as_an_order(client, owner_headers, once):
    """发货之后订单不能再走取消流程（否则库存账目会对不上）。"""
    order_id = once["reserve"]("CC-STATE-1", quantity=2)
    shipment = create_shipment(client, owner_headers, order_id).json()
    pick(client, owner_headers, shipment["id"], once["sku"]["barcode"], 2)
    pack(client, owner_headers, shipment["id"])
    assert ship(client, owner_headers, shipment["id"]).status_code == 200

    response = client.post(
        f"{API}/orders/{order_id}/cancel", json={"reason": "买家反悔"}, headers=owner_headers
    )
    assert response.status_code == 409
    assert response.json()["code"] == 40912
