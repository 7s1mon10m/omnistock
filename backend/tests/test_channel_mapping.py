"""Channels, shops and the channel-product mapping.

The mapping is what lets three platforms with three different product codes all
draw on one internal SKU — and therefore one stock pool.
"""

from __future__ import annotations

from conftest import API, create_channel, create_mapping, create_shop, uniq


def test_create_channel_and_reject_duplicate_code(client, operator_headers):
    channel = create_channel(client, operator_headers, code="TB-DUP", name="淘宝")

    again = client.post(
        f"{API}/channels",
        json={"code": "TB-DUP", "name": "重复", "platform": "taobao"},
        headers=operator_headers,
    )
    assert again.status_code == 409
    assert again.json()["code"] == 40916
    assert channel["platform"] == "taobao"


def test_shop_is_scoped_to_its_channel(client, operator_headers):
    channel = create_channel(client, operator_headers)
    shop = create_shop(client, operator_headers, channel["id"], code="S1")

    duplicated = client.post(
        f"{API}/channels/{channel['id']}/shops",
        json={"code": "S1", "name": "重复店铺"},
        headers=operator_headers,
    )
    assert duplicated.status_code == 409
    assert duplicated.json()["code"] == 40917

    listed = client.get(f"{API}/channels/{channel['id']}/shops", headers=operator_headers).json()
    assert [item["code"] for item in listed] == ["S1"]
    assert listed[0]["id"] == shop["id"]


def test_creating_a_shop_on_an_unknown_channel_returns_404(client, operator_headers):
    response = client.post(
        f"{API}/channels/987654/shops", json={"code": "NOPE"}, headers=operator_headers
    )
    assert response.status_code == 404
    assert response.json()["code"] == 40420


def test_the_same_internal_sku_can_back_three_platform_codes(client, operator_headers, catalog):
    """内部 SKU TSHIRT-WHITE-L ← 淘宝 TB-100238 / 抖音 DY-883021 / Shopify SHOP-TS-001"""
    sku_id = catalog["sku"]["id"]
    tag = uniq("M")

    taobao = create_channel(client, operator_headers, code=f"TB-{tag}", platform="taobao")
    douyin = create_channel(client, operator_headers, code=f"DY-{tag}", platform="douyin")
    shopify = create_channel(client, operator_headers, code=f"SHOP-{tag}", platform="shopify")

    for channel, code in ((taobao, "TB-100238"), (douyin, "DY-883021"), (shopify, "SHOP-TS-001")):
        response = create_mapping(client, operator_headers, channel["id"], code, sku_id)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["sku_id"] == sku_id
        assert body["sku_code"] == catalog["sku"]["sku_code"]

    # All three resolve to the same SKU, so an order from any platform draws on
    # the same stock pool.
    listed = client.get(
        f"{API}/channel-products?sku_id={sku_id}&page_size=200", headers=operator_headers
    ).json()
    codes = {item["channel_code"] for item in listed["items"]}
    assert {taobao["code"], douyin["code"], shopify["code"]} <= codes


def test_a_channel_product_code_cannot_map_to_two_skus(client, operator_headers, catalog):
    channel = create_channel(client, operator_headers)
    first = create_mapping(client, operator_headers, channel["id"], "DUP-CODE", catalog["sku"]["id"])
    assert first.status_code == 201

    again = create_mapping(client, operator_headers, channel["id"], "DUP-CODE", catalog["sku"]["id"])
    assert again.status_code == 409
    assert again.json()["code"] == 40918

    # The same code on a different channel is fine — codes are per channel.
    other = create_channel(client, operator_headers)
    assert create_mapping(
        client, operator_headers, other["id"], "DUP-CODE", catalog["sku"]["id"]
    ).status_code == 201


def test_mapping_to_an_unknown_sku_returns_404(client, operator_headers):
    channel = create_channel(client, operator_headers)
    response = create_mapping(client, operator_headers, channel["id"], "GHOST", 987654)
    assert response.status_code == 404
    assert response.json()["code"] == 40411


def test_mapping_can_be_retargeted_and_removed(client, operator_headers, catalog):
    channel = create_channel(client, operator_headers)
    created = create_mapping(
        client, operator_headers, channel["id"], "MOVE-ME", catalog["sku"]["id"]
    ).json()

    renamed = client.patch(
        f"{API}/channel-products/{created['id']}",
        json={"channel_title": "改名后的渠道商品名", "is_active": False},
        headers=operator_headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["channel_title"] == "改名后的渠道商品名"
    assert renamed.json()["is_active"] is False

    removed = client.delete(f"{API}/channel-products/{created['id']}", headers=operator_headers)
    assert removed.status_code == 204
    assert client.get(
        f"{API}/channel-products?keyword=MOVE-ME", headers=operator_headers
    ).json()["total"] == 0


def test_warehouse_role_cannot_manage_channels(client, warehouse_headers):
    response = client.post(
        f"{API}/channels", json={"code": "NOPE", "name": "越权"}, headers=warehouse_headers
    )
    assert response.status_code == 403
    assert response.json()["code"] == 40301
