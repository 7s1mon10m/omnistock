"""渠道适配器：配置、字段映射与幂等同步。

适配器这一层的价值是把「平台千奇百怪的字段名和单位」挡在门口：淘宝的金额
是「元」的字符串，抖音的金额是「分」的整数。下游的占用、去重、异常逻辑完全
不需要知道订单来自哪个平台。

同步的幂等性与 M2 的导入一致：平台把同一批订单又推一遍，不该重复扣库存。
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
    create_warehouse,
    uniq,
)


@pytest.fixture()
def shop(client, owner_headers, monkeypatch):
    from app.core.config import settings

    tag = uniq("ADP")
    warehouse = create_warehouse(client, owner_headers, name=f"适配仓{tag}", code=f"WH-{tag}")
    monkeypatch.setattr(settings, "DEFAULT_WAREHOUSE_CODE", warehouse["code"])

    spu = create_spu(client, owner_headers, f"SPU-{tag}", "适配商品")
    sku = create_sku(
        client, owner_headers, spu["id"], sku_code=f"SKU-{tag}", safety_qty=0
    )
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 50, "备货")

    channel = create_channel(client, owner_headers, name=f"适配渠道{tag}", platform="taobao")
    create_mapping(client, owner_headers, channel["id"], f"AD{tag}", sku["id"])
    return {
        "warehouse": warehouse,
        "sku": sku,
        "channel": channel,
        "headers": owner_headers,
        "tag": tag,
    }


def configure(client, headers, channel_id: int, key: str = "taobao", enabled: bool = True):
    response = client.post(
        f"{API}/channel-adapters",
        json={"channel_id": channel_id, "adapter_key": key, "enabled": enabled},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def sync(client, headers, adapter_id: int, payload: dict):
    return client.post(f"{API}/channel-adapters/{adapter_id}/sync", json=payload, headers=headers)


# ------------------------------------------------------------------ 注册表
def test_the_registry_lists_file_and_api_adapters(client, owner_headers):
    rows = client.get(f"{API}/channel-adapters/descriptors", headers=owner_headers).json()
    kinds = {row["key"]: row["kind"] for row in rows}
    assert kinds["csv"] == "file"
    assert kinds["json"] == "file"
    assert kinds["taobao"] == "api"
    assert kinds["douyin"] == "api"


# -------------------------------------------------------------------- 配置
def test_a_channel_can_be_bound_to_an_adapter(client, owner_headers, shop):
    row = configure(client, owner_headers, shop["channel"]["id"])
    assert row["adapter_key"] == "taobao"
    assert row["enabled"] is True
    assert row["last_sync_status"] == "never"


def test_an_unknown_adapter_key_is_refused(client, owner_headers, shop):
    response = client.post(
        f"{API}/channel-adapters",
        json={"channel_id": shop["channel"]["id"], "adapter_key": "weird-platform"},
        headers=owner_headers,
    )
    assert response.status_code == 404
    assert response.json()["code"] == 40490


def test_a_channel_can_only_have_one_adapter(client, owner_headers, shop):
    configure(client, owner_headers, shop["channel"]["id"])
    response = client.post(
        f"{API}/channel-adapters",
        json={"channel_id": shop["channel"]["id"], "adapter_key": "douyin"},
        headers=owner_headers,
    )
    assert response.status_code == 409


def test_syncing_a_disabled_adapter_is_refused(client, owner_headers, shop):
    row = configure(client, owner_headers, shop["channel"]["id"], enabled=False)
    response = sync(client, owner_headers, row["id"], {"orders": []})
    assert response.status_code == 424
    assert response.json()["code"] == 42403


# -------------------------------------------------------------------- 同步
def test_taobao_orders_are_mapped_and_reserved(client, owner_headers, shop):
    adapter = configure(client, owner_headers, shop["channel"]["id"], "taobao")
    payload = {
        "orders": [
            {
                "tid": f"TB-{shop['tag']}-1",
                "pay_time": "2026-10-02 10:00:00",
                "buyer_nick": "买家甲",
                "orders": [{"outer_sku_id": f"AD{shop['tag']}", "num": 3, "price": "99.00"}],
            }
        ]
    }
    response = sync(client, owner_headers, adapter["id"], payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_orders"] == 1
    assert body["failed_rows"] == 0

    # 占用真的发生了
    stock = [
        row
        for row in client.get(f"{API}/inventory?page_size=200", headers=owner_headers).json()["items"]
        if row["sku_id"] == shop["sku"]["id"] and row["warehouse_id"] == shop["warehouse"]["id"]
    ][0]
    assert stock["reserved_qty"] == 3


def test_the_channel_code_comes_from_configuration_not_the_payload(client, owner_headers, shop):
    """平台不知道我们内部怎么称呼这个渠道，渠道身份必须由配置给出。"""
    adapter = configure(client, owner_headers, shop["channel"]["id"], "taobao")
    # 响应里完全没有 shop_code / seller_nick
    payload = {
        "orders": [
            {
                "tid": f"TB-{shop['tag']}-2",
                "orders": [{"outer_sku_id": f"AD{shop['tag']}", "num": 1, "price": "10.00"}],
            }
        ]
    }
    response = sync(client, owner_headers, adapter["id"], payload)
    assert response.status_code == 200, response.text
    assert response.json()["created_orders"] == 1


def test_syncing_the_same_batch_twice_does_not_double_reserve(client, owner_headers, shop):
    adapter = configure(client, owner_headers, shop["channel"]["id"], "taobao")
    payload = {
        "orders": [
            {
                "tid": f"TB-{shop['tag']}-3",
                "orders": [{"outer_sku_id": f"AD{shop['tag']}", "num": 4, "price": "20.00"}],
            }
        ]
    }
    assert sync(client, owner_headers, adapter["id"], payload).json()["created_orders"] == 1

    again = sync(client, owner_headers, adapter["id"], payload)
    assert again.status_code == 200
    assert again.json()["created_orders"] == 0
    assert again.json()["duplicate_orders"] == 1

    stock = [
        row
        for row in client.get(f"{API}/inventory?page_size=200", headers=owner_headers).json()["items"]
        if row["sku_id"] == shop["sku"]["id"] and row["warehouse_id"] == shop["warehouse"]["id"]
    ][0]
    assert stock["reserved_qty"] == 4, "重复推送绝不能重复占用"


def test_a_repeat_sync_is_reported_as_ok_not_failed(client, owner_headers, shop):
    """全是重复说明同步正常工作，不该把适配器标成失败。"""
    adapter = configure(client, owner_headers, shop["channel"]["id"], "taobao")
    payload = {
        "orders": [
            {
                "tid": f"TB-{shop['tag']}-4",
                "orders": [{"outer_sku_id": f"AD{shop['tag']}", "num": 1, "price": "5.00"}],
            }
        ]
    }
    sync(client, owner_headers, adapter["id"], payload)
    sync(client, owner_headers, adapter["id"], payload)

    rows = client.get(
        f"{API}/channel-adapters?channel_id={shop['channel']['id']}", headers=owner_headers
    ).json()
    assert rows[0]["last_sync_status"] == "ok"


def test_a_bad_row_is_reported_not_swallowed(client, owner_headers, shop):
    adapter = configure(client, owner_headers, shop["channel"]["id"], "taobao")
    # 这一行没有商品行，应该被报出来而不是让整批静默失败
    payload = {"orders": [{"tid": f"TB-{shop['tag']}-bad"}]}
    response = sync(client, owner_headers, adapter["id"], payload)
    assert response.status_code == 200
    assert response.json()["failed_rows"] == 1

    rows = client.get(
        f"{API}/channel-adapters?channel_id={shop['channel']['id']}", headers=owner_headers
    ).json()
    assert rows[0]["last_sync_status"] in ("failed", "partial")


def test_douyin_amounts_are_already_in_cents(client, owner_headers, shop):
    """抖音的 pay_amount 是「分」，不能再乘 100 —— 这是最容易搞错的一处。"""
    from app.adapters import registry

    adapter = registry.get_api_adapter("douyin")
    parsed = adapter.parse(
        b'{"orders":[{"order_id":"DY-1","items":[{"outer_sku_id":"X","item_num":2,"pay_amount":9900}]}]}'
    )
    assert len(parsed.orders) == 1
    # 9900 分 = 99 元，直接采用
    assert parsed.orders[0].items[0].unit_price_cents == 9900
    assert parsed.orders[0].items[0].quantity == 2


def test_taobao_yuan_strings_are_converted_to_cents(client, owner_headers, shop):
    """淘宝的 price 是「元」的字符串，必须转成分。"""
    from app.adapters import registry

    adapter = registry.get_api_adapter("taobao")
    parsed = adapter.parse(
        b'{"orders":[{"tid":"TB-1","orders":[{"outer_sku_id":"X","num":2,"price":"99.00"}]}]}'
    )
    assert parsed.orders[0].items[0].unit_price_cents == 9900


def test_a_malformed_payload_is_rejected_clearly(client, owner_headers, shop):
    adapter = configure(client, owner_headers, shop["channel"]["id"], "taobao")
    response = sync(client, owner_headers, adapter["id"], {"orders": "not-a-list"})
    assert response.status_code == 422


def test_a_sync_writes_an_order_sync_log(client, owner_headers, shop):
    adapter = configure(client, owner_headers, shop["channel"]["id"], "taobao")
    payload = {
        "orders": [
            {
                "tid": f"TB-{shop['tag']}-5",
                "orders": [{"outer_sku_id": f"AD{shop['tag']}", "num": 1, "price": "1.00"}],
            }
        ]
    }
    body = sync(client, owner_headers, adapter["id"], payload).json()
    assert body["sync_log_id"] is not None


def test_only_an_admin_may_configure_adapters(client, operator_headers, shop):
    response = client.post(
        f"{API}/channel-adapters",
        json={"channel_id": shop["channel"]["id"], "adapter_key": "taobao"},
        headers=operator_headers,
    )
    assert response.status_code == 403
