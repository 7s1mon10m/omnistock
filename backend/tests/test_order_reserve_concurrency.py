"""多平台同时下单：先到先得，绝不超卖。

The interesting case is two channels selling the same SKU from the same pool —
whichever order arrives first holds the stock, and the loser becomes an
exception order rather than an oversell.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

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

SELLABLE = 10
OVERSELL_ATTEMPTS = 20


def _drain_to(client, catalog, keep: int) -> None:
    """Leave exactly ``keep`` sellable units (catalog starts at 100, safety 0).

    Stock adjustments need the warehouse persona, so this deliberately uses the
    catalog's owner headers rather than whoever is driving the order flow.
    """
    headers = catalog["headers"]
    current = stock_of(client, headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    delta = keep - current["available_qty"]
    if delta:
        adjust_stock(
            client, headers, catalog["sku"]["id"], catalog["warehouse"]["id"], delta, "调整可售量"
        )


def _channels(client, headers, catalog, count: int = 2):
    """``count`` channels all mapped to the same internal SKU."""
    result = []
    for index in range(count):
        channel = create_channel(
            client, headers, code=uniq(f"C{index}"), platform="taobao" if index == 0 else "douyin"
        )
        code = uniq("P")
        create_mapping(client, headers, channel["id"], code, catalog["sku"]["id"])
        result.append((channel, code))
    return result


def test_sequential_boundary_hands_out_exactly_the_sellable_units(
    client, operator_headers, catalog
):
    _drain_to(client, catalog, SELLABLE)
    (channel, code), _ = _channels(client, operator_headers, catalog)

    for index in range(SELLABLE + 3):
        import_orders(
            client,
            operator_headers,
            [
                order_payload(
                    channel["code"],
                    f"BOUND-{index}",
                    [{"channel_product_code": code, "quantity": 1}],
                )
            ],
        )

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == SELLABLE
    assert stock["available_qty"] == 0

    reserved = client.get(
        f"{API}/orders?channel_id={channel['id']}&status=reserved&page_size=200",
        headers=operator_headers,
    ).json()
    exception = client.get(
        f"{API}/orders?channel_id={channel['id']}&status=exception&page_size=200",
        headers=operator_headers,
    ).json()
    assert reserved["total"] == SELLABLE
    assert exception["total"] == 3


def test_concurrent_orders_from_two_channels_never_oversell(client, operator_headers, catalog):
    _drain_to(client, catalog, SELLABLE)
    (channel_a, code_a), (channel_b, code_b) = _channels(
        client, operator_headers, catalog, count=2
    )

    def attempt(index: int) -> int:
        channel, code = (channel_a, code_a) if index % 2 == 0 else (channel_b, code_b)
        try:
            response = import_orders(
                client,
                operator_headers,
                [
                    order_payload(
                        channel["code"],
                        f"RACE-{index}",
                        [{"channel_product_code": code, "quantity": 1}],
                    )
                ],
            )
            return response.status_code
        except Exception:  # pragma: no cover - a lost race may surface as a transport error
            return 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(attempt, range(OVERSELL_ATTEMPTS)))
    assert len(statuses) == OVERSELL_ATTEMPTS

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] <= SELLABLE, f"超卖了：reserved={stock['reserved_qty']}"
    assert stock["available_qty"] >= 0

    # Whatever was not reserved must be sitting in an exception order, not lost.
    # Filter by *this* test's channels: order numbers are only unique per channel.
    mine_reserved: list[dict] = []
    mine_exception: list[dict] = []
    for channel in (channel_a, channel_b):
        mine_reserved += client.get(
            f"{API}/orders?channel_id={channel['id']}&status=reserved&page_size=200",
            headers=operator_headers,
        ).json()["items"]
        mine_exception += client.get(
            f"{API}/orders?channel_id={channel['id']}&status=exception&page_size=200",
            headers=operator_headers,
        ).json()["items"]

    assert stock["reserved_qty"] == len(mine_reserved), "占用数与订单数对不上"
    assert len(mine_reserved) + len(mine_exception) == OVERSELL_ATTEMPTS
    assert len(mine_reserved) <= SELLABLE


def test_one_order_needing_more_than_available_does_not_partially_reserve(
    client, operator_headers, catalog
):
    """默认 exception 策略下，缺货是整单失败而不是占一半。"""
    _drain_to(client, catalog, 5)
    (channel, code), _ = _channels(client, operator_headers, catalog)

    body = import_orders(
        client,
        operator_headers,
        [order_payload(channel["code"], "WHOLE-1", [{"channel_product_code": code, "quantity": 8}])],
    ).json()
    assert body["exception_orders"] == 1
    assert body["reserved_orders"] == 0

    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == 0
    assert stock["available_qty"] == 5, "整单失败不应吃掉任何可售库存"


def test_a_multi_line_order_is_all_or_nothing(client, operator_headers, catalog):
    """一张订单里有两个 SKU，其中一个不够，整单都不占用。"""
    tag = uniq("ML")
    spu_b = create_spu(client, operator_headers, f"SPU-{tag}", "第二个商品")
    sku_b = create_sku(
        client, operator_headers, spu_b["id"], sku_code=f"SKU-B-{tag}", safety_qty=0
    )
    adjust_stock(client, catalog["headers"], sku_b["id"], catalog["warehouse"]["id"], 1, "仅 1 件")

    (channel, code_a), _ = _channels(client, operator_headers, catalog)
    code_b = uniq("P")
    create_mapping(client, operator_headers, channel["id"], code_b, sku_b["id"])

    body = import_orders(
        client,
        operator_headers,
        [
            order_payload(
                channel["code"],
                "MULTI-1",
                [
                    {"channel_product_code": code_a, "quantity": 2},
                    {"channel_product_code": code_b, "quantity": 5},
                ],
            )
        ],
    ).json()
    assert body["exception_orders"] == 1

    stock_a = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    stock_b = stock_of(client, operator_headers, sku_b["id"], catalog["warehouse"]["id"])
    assert stock_a["reserved_qty"] == 0
    assert stock_b["reserved_qty"] == 0
