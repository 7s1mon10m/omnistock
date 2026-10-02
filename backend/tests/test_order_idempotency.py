"""Idempotency: a re-synced order must never book stock twice.

This is the single most important rule in the order pipeline — channel webhooks
retry, exports overlap, and a duplicate that silently reserves stock again shows
up days later as a phantom shortage.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from conftest import (
    API,
    create_channel,
    create_mapping,
    import_orders,
    order_payload,
    stock_of,
    uniq,
)


def _setup(client, headers, catalog):
    channel = create_channel(client, headers, code=uniq("ID"))
    code = uniq("P")
    create_mapping(client, headers, channel["id"], code, catalog["sku"]["id"])
    return channel, code


def test_importing_the_same_order_twice_reserves_stock_once(client, operator_headers, catalog):
    channel, code = _setup(client, operator_headers, catalog)
    payload = [order_payload(channel["code"], "IDEM-1", [{"channel_product_code": code, "quantity": 5}])]

    first = import_orders(client, operator_headers, payload).json()
    assert first["created_orders"] == 1
    assert first["duplicate_orders"] == 0

    second = import_orders(client, operator_headers, payload).json()
    assert second["created_orders"] == 0
    assert second["duplicate_orders"] == 1

    orders = client.get(f"{API}/orders?keyword=IDEM-1", headers=operator_headers).json()
    assert orders["total"] == 1

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == 5, "重复同步把库存扣了两次"
    assert stock["on_hand_qty"] == 100


def test_the_duplicate_is_visible_in_the_sync_log(client, operator_headers, catalog):
    channel, code = _setup(client, operator_headers, catalog)
    payload = [order_payload(channel["code"], "IDEM-LOG", [{"channel_product_code": code, "quantity": 1}])]

    import_orders(client, operator_headers, payload)
    import_orders(client, operator_headers, payload)

    logs = client.get(
        f"{API}/orders/sync-logs?channel_order_no=IDEM-LOG", headers=operator_headers
    ).json()
    results = sorted(item["result"] for item in logs["items"])
    assert results == ["created", "duplicate"]

    duplicate = next(item for item in logs["items"] if item["result"] == "duplicate")
    assert duplicate["order_id"] is not None
    assert "未重复占用" in duplicate["message"]


def test_a_duplicate_inside_one_file_is_skipped(client, operator_headers, catalog):
    channel, code = _setup(client, operator_headers, catalog)
    same = order_payload(channel["code"], "IDEM-SAME-FILE", [{"channel_product_code": code, "quantity": 2}])

    body = import_orders(client, operator_headers, [same, same]).json()
    assert body["created_orders"] == 1
    assert body["duplicate_orders"] == 1

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == 2


def test_the_same_order_number_on_two_channels_is_two_orders(client, operator_headers, catalog):
    """渠道订单号只在渠道内唯一 —— 淘宝的 123 和抖音的 123 是两单。"""
    code_a = uniq("P")
    code_b = uniq("P")
    channel_a = create_channel(client, operator_headers, code=uniq("A"), platform="taobao")
    channel_b = create_channel(client, operator_headers, code=uniq("B"), platform="douyin")
    create_mapping(client, operator_headers, channel_a["id"], code_a, catalog["sku"]["id"])
    create_mapping(client, operator_headers, channel_b["id"], code_b, catalog["sku"]["id"])

    body = import_orders(
        client,
        operator_headers,
        [
            order_payload(channel_a["code"], "SHARED-1", [{"channel_product_code": code_a, "quantity": 1}]),
            order_payload(channel_b["code"], "SHARED-1", [{"channel_product_code": code_b, "quantity": 1}]),
        ],
    ).json()

    assert body["created_orders"] == 2
    assert body["duplicate_orders"] == 0

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == 2


def test_a_replayed_import_does_not_double_book(client, operator_headers, catalog):
    """Simulates a channel that retried the exact same push."""
    channel, code = _setup(client, operator_headers, catalog)
    payload = [order_payload(channel["code"], "REPLAY-1", [{"channel_product_code": code, "quantity": 3}])]

    for _ in range(4):
        import_orders(client, operator_headers, payload)

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == 3
    orders = client.get(f"{API}/orders?keyword=REPLAY-1", headers=operator_headers).json()
    assert orders["total"] == 1


def test_concurrent_imports_of_the_same_order_create_one_order(client, operator_headers, catalog):
    """Two sync workers racing on the same order must not both insert it."""
    channel, code = _setup(client, operator_headers, catalog)
    payload = [
        order_payload(channel["code"], "RACE-1", [{"channel_product_code": code, "quantity": 4}])
    ]

    def attempt(_: int) -> int:
        try:
            return import_orders(client, operator_headers, payload).status_code
        except Exception:  # pragma: no cover - a lost race may surface as a transport error
            return 0

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(attempt, range(4)))

    orders = client.get(f"{API}/orders?keyword=RACE-1", headers=operator_headers).json()
    assert orders["total"] == 1, "并发同步创建了重复订单"

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == 4, "并发同步把库存扣了多次"
