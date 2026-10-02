"""Order lifecycle: shortage → exception, retry, cancel, pay, bundle explosion."""

from __future__ import annotations

from app.core.config import settings
from conftest import (
    API,
    adjust_stock,
    create_channel,
    create_mapping,
    create_sku,
    create_spu,
    import_orders,
    order_payload,
    stock_of,
    uniq,
)


def _setup(client, headers, catalog):
    channel = create_channel(client, headers, code=uniq("LC"))
    code = uniq("P")
    create_mapping(client, headers, channel["id"], code, catalog["sku"]["id"])
    return channel, code


def _first_order(client, headers, keyword: str) -> dict:
    listed = client.get(f"{API}/orders?keyword={keyword}", headers=headers).json()
    assert listed["total"] == 1, listed
    order_id = listed["items"][0]["id"]
    return client.get(f"{API}/orders/{order_id}", headers=headers).json()


# ------------------------------------------------------------------ shortage
def test_a_shortage_turns_the_whole_order_into_an_exception(client, operator_headers, catalog):
    channel, code = _setup(client, operator_headers, catalog)
    # 100 on hand, ask for 150: the exception strategy refuses everything.
    body = import_orders(
        client,
        operator_headers,
        [order_payload(channel["code"], "SHORT-1", [{"channel_product_code": code, "quantity": 150}])],
    ).json()
    assert body["created_orders"] == 1
    assert body["exception_orders"] == 1
    assert body["reserved_orders"] == 0

    order = _first_order(client, operator_headers, "SHORT-1")
    assert order["status"] == "exception"
    assert order["open_exceptions"] == 1
    assert order["reservations"] == [], "整单失败时不应该有部分占用"

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == 0

    exceptions = client.get(
        f"{API}/orders/exceptions?order_id={order['id']}", headers=operator_headers
    ).json()
    row = exceptions["items"][0]
    assert row["type"] == "stock_shortage"
    assert row["required_qty"] == 150
    assert row["available_qty"] == 100
    assert row["shortage_qty"] == 50


def test_restocking_then_retrying_reserves_the_order(client, operator_headers, catalog):
    channel, code = _setup(client, operator_headers, catalog)
    import_orders(
        client,
        operator_headers,
        [order_payload(channel["code"], "RETRY-1", [{"channel_product_code": code, "quantity": 150}])],
    )
    order = _first_order(client, operator_headers, "RETRY-1")
    assert order["status"] == "exception"

    adjust_stock(
        client, catalog["headers"], catalog["sku"]["id"], catalog["warehouse"]["id"], 100, "补货"
    )

    retried = client.post(
        f"{API}/orders/{order['id']}/retry-reserve", headers=operator_headers
    )
    assert retried.status_code == 200, retried.text
    body = retried.json()
    assert body["order"]["status"] == "reserved"
    assert body["order"]["reservations"][0]["quantity"] == 150
    assert body["message"] == "已补齐占用"

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == 150


def test_retrying_without_restocking_keeps_it_in_exception(client, operator_headers, catalog):
    channel, code = _setup(client, operator_headers, catalog)
    import_orders(
        client,
        operator_headers,
        [order_payload(channel["code"], "RETRY-2", [{"channel_product_code": code, "quantity": 500}])],
    )
    order = _first_order(client, operator_headers, "RETRY-2")

    body = client.post(
        f"{API}/orders/{order['id']}/retry-reserve", headers=operator_headers
    ).json()
    assert body["order"]["status"] == "exception"
    assert body["message"] == "仍有 SKU 缺货"
    # The exception list reflects the latest attempt, it does not pile up.
    assert body["order"]["open_exceptions"] == 1


def test_partial_strategy_reserves_what_it_can(client, operator_headers, catalog, monkeypatch):
    monkeypatch.setattr(settings, "ORDER_SHORTAGE_STRATEGY", "partial")
    channel, code = _setup(client, operator_headers, catalog)

    body = import_orders(
        client,
        operator_headers,
        [order_payload(channel["code"], "PARTIAL-1", [{"channel_product_code": code, "quantity": 130}])],
    ).json()
    assert body["exception_orders"] == 1  # still short, so still flagged

    order = _first_order(client, operator_headers, "PARTIAL-1")
    assert order["reservations"][0]["quantity"] == 100, "应该把能占的 100 件先占上"
    assert order["open_exceptions"] == 1

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == 100
    assert stock["available_qty"] == 0


# --------------------------------------------------------------------- cancel
def test_cancelling_releases_exactly_what_was_reserved(client, operator_headers, catalog):
    channel, code = _setup(client, operator_headers, catalog)
    import_orders(
        client,
        operator_headers,
        [order_payload(channel["code"], "CANCEL-1", [{"channel_product_code": code, "quantity": 7}])],
    )
    order = _first_order(client, operator_headers, "CANCEL-1")
    assert order["status"] == "reserved"

    response = client.post(
        f"{API}/orders/{order['id']}/cancel", json={"reason": "客户改主意"}, headers=operator_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["order"]["status"] == "cancelled"
    assert response.json()["released"][0]["quantity"] == 7

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == 0
    assert stock["on_hand_qty"] == 100


def test_cancelling_an_exception_order_closes_its_exceptions(client, operator_headers, catalog):
    channel, code = _setup(client, operator_headers, catalog)
    import_orders(
        client,
        operator_headers,
        [order_payload(channel["code"], "CANCEL-2", [{"channel_product_code": code, "quantity": 900}])],
    )
    order = _first_order(client, operator_headers, "CANCEL-2")
    assert order["open_exceptions"] == 1

    client.post(f"{API}/orders/{order['id']}/cancel", json={}, headers=operator_headers)

    close_open = client.get(f"{API}/orders/exceptions?status=open", headers=operator_headers).json()
    assert all(item["order_id"] != order["id"] for item in close_open["items"])

    after = client.get(f"{API}/orders/{order['id']}", headers=operator_headers).json()
    assert after["status"] == "cancelled"
    assert after["open_exceptions"] == 0


def test_cancelling_twice_is_refused(client, operator_headers, catalog):
    channel, code = _setup(client, operator_headers, catalog)
    import_orders(
        client,
        operator_headers,
        [order_payload(channel["code"], "CANCEL-3", [{"channel_product_code": code, "quantity": 1}])],
    )
    order = _first_order(client, operator_headers, "CANCEL-3")

    assert client.post(
        f"{API}/orders/{order['id']}/cancel", json={}, headers=operator_headers
    ).status_code == 200
    again = client.post(f"{API}/orders/{order['id']}/cancel", json={}, headers=operator_headers)
    assert again.status_code == 409
    assert again.json()["code"] == 40912


def test_a_cancelled_order_does_not_block_a_fresh_sync(client, operator_headers, catalog):
    """取消后再同步同一单号，应该被当成重复而不会复活。"""
    channel, code = _setup(client, operator_headers, catalog)
    payload = [order_payload(channel["code"], "CANCEL-4", [{"channel_product_code": code, "quantity": 2}])]
    import_orders(client, operator_headers, payload)
    order = _first_order(client, operator_headers, "CANCEL-4")
    client.post(f"{API}/orders/{order['id']}/cancel", json={}, headers=operator_headers)

    body = import_orders(client, operator_headers, payload).json()
    assert body["duplicate_orders"] == 1

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == 0


# ------------------------------------------------------------------ pay flow
def test_an_unpaid_order_reserves_nothing_until_it_is_marked_paid(
    client, operator_headers, catalog, monkeypatch
):
    monkeypatch.setattr(settings, "ORDER_IMPORT_ASSUME_PAID", False)
    channel, code = _setup(client, operator_headers, catalog)

    import_orders(
        client,
        operator_headers,
        [order_payload(channel["code"], "PAY-1", [{"channel_product_code": code, "quantity": 6}])],
    )
    order = _first_order(client, operator_headers, "PAY-1")
    assert order["status"] == "pending_payment"
    assert order["reservations"] == []

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == 0

    paid = client.post(
        f"{API}/orders/{order['id']}/mark-paid", json={}, headers=operator_headers
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["order"]["status"] == "reserved"
    assert paid.json()["order"]["paid_at"] is not None

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == 6


def test_marking_an_already_paid_order_paid_again_is_refused(client, operator_headers, catalog):
    channel, code = _setup(client, operator_headers, catalog)
    import_orders(
        client,
        operator_headers,
        [order_payload(channel["code"], "PAY-2", [{"channel_product_code": code, "quantity": 1}])],
    )
    order = _first_order(client, operator_headers, "PAY-2")

    again = client.post(f"{API}/orders/{order['id']}/mark-paid", json={}, headers=operator_headers)
    assert again.status_code == 409
    assert again.json()["code"] == 40912


# -------------------------------------------------------------------- bundles
def test_a_bundle_order_reserves_its_components(client, operator_headers, catalog):
    """下单买套装，占用的是拆解后的实际 SKU。"""
    tag = uniq("B")
    component_spu = create_spu(client, operator_headers, f"SPU-A-{tag}", "洗发水")
    component = create_sku(
        client, operator_headers, component_spu["id"], sku_code=f"SHAMPOO-{tag}", safety_qty=0
    )
    adjust_stock(
        client, catalog["headers"], component["id"], catalog["warehouse"]["id"], 50, "备货"
    )

    bundle_spu = create_spu(client, operator_headers, f"SPU-B-{tag}", "洗护套装", type_="bundle")
    bundle = create_sku(
        client, operator_headers, bundle_spu["id"], sku_code=f"SET-{tag}", safety_qty=0
    )
    set_components = client.put(
        f"{API}/bundles/{bundle['id']}/components",
        json={"components": [{"component_sku_id": component["id"], "quantity": 2}]},
        headers=operator_headers,
    )
    assert set_components.status_code == 200, set_components.text

    channel = create_channel(client, operator_headers, code=uniq("BD"))
    mapping_code = uniq("P")
    create_mapping(client, operator_headers, channel["id"], mapping_code, bundle["id"])

    import_orders(
        client,
        operator_headers,
        [order_payload(channel["code"], "BUNDLE-1", [{"channel_product_code": mapping_code, "quantity": 3}])],
    )

    order = _first_order(client, operator_headers, "BUNDLE-1")
    assert order["status"] == "reserved"
    assert order["is_bundle"] is True

    # 3 sets x 2 units per set = 6 of the component.
    assert len(order["reservations"]) == 1
    assert order["reservations"][0]["sku_id"] == component["id"]
    assert order["reservations"][0]["quantity"] == 6

    # The bundle SKU itself never holds stock.
    bundle_rows = client.get(
        f"{API}/inventory?sku_id={bundle['id']}", headers=operator_headers
    ).json()
    assert all(row["reserved_qty"] == 0 for row in bundle_rows["items"])


def test_cancelling_a_bundle_order_releases_the_components(client, operator_headers, catalog):
    tag = uniq("BC")
    c_spu = create_spu(client, operator_headers, f"SPU-C-{tag}", "护发素")
    component = create_sku(
        client, operator_headers, c_spu["id"], sku_code=f"COND-{tag}", safety_qty=0
    )
    adjust_stock(client, catalog["headers"], component["id"], catalog["warehouse"]["id"], 30, "备货")

    b_spu = create_spu(client, operator_headers, f"SPU-D-{tag}", "套装二", type_="bundle")
    bundle = create_sku(client, operator_headers, b_spu["id"], sku_code=f"SET2-{tag}", safety_qty=0)
    client.put(
        f"{API}/bundles/{bundle['id']}/components",
        json={"components": [{"component_sku_id": component["id"], "quantity": 1}]},
        headers=operator_headers,
    )

    channel = create_channel(client, operator_headers, code=uniq("BE"))
    mapping_code = uniq("P")
    create_mapping(client, operator_headers, channel["id"], mapping_code, bundle["id"])
    import_orders(
        client,
        operator_headers,
        [order_payload(channel["code"], "BUNDLE-2", [{"channel_product_code": mapping_code, "quantity": 4}])],
    )

    order = _first_order(client, operator_headers, "BUNDLE-2")
    assert order["reservations"][0]["quantity"] == 4

    released = client.post(
        f"{API}/orders/{order['id']}/cancel", json={}, headers=operator_headers
    ).json()

    # The release is derived from the ledger, so it releases exactly 4 — even
    # though the bundle definition is what produced that number.
    assert released["released"][0]["quantity"] == 4
    stock = stock_of(client, operator_headers, component["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == 0
