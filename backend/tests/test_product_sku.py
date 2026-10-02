"""SPU / SKU / barcode maintenance."""

from __future__ import annotations

from conftest import API, create_sku, create_spu, create_warehouse


def test_create_spu_and_reject_duplicate_code(client, operator_headers):
    spu = create_spu(client, operator_headers, "SPU-OK-1", "基础款卫衣")
    assert spu["code"] == "SPU-OK-1"
    assert spu["type"] == "single"
    assert spu["sku_count"] == 0

    again = client.post(
        f"{API}/spus",
        json={"code": "SPU-OK-1", "name": "重复编码"},
        headers=operator_headers,
    )
    assert again.status_code == 409
    assert again.json()["code"] == 40901


def test_create_sku_generates_a_readable_code_for_ascii_specs(client, operator_headers):
    spu = create_spu(client, operator_headers, "TSHIRT-A", "纯棉短袖")
    sku = create_sku(
        client, operator_headers, spu["id"], spec_json={"color": "WHITE", "size": "L"}
    )
    assert sku["sku_code"] == "SKU-TSHIRT-A-WHITE-L"
    assert sku["display_name"] == "纯棉短袖 WHITE / L"


def test_non_ascii_specs_fall_back_to_a_running_number(client, operator_headers):
    spu = create_spu(client, operator_headers, "TSHIRT-B", "纯棉短袖")
    first = create_sku(client, operator_headers, spu["id"], spec_json={"color": "白", "size": "L"})
    second = create_sku(client, operator_headers, spu["id"], spec_json={"color": "黑", "size": "L"})

    # Chinese spec values would make an unusable SKU code, so a序号 is used.
    assert first["sku_code"] == "SKU-TSHIRT-B-01"
    assert second["sku_code"] == "SKU-TSHIRT-B-02"
    assert first["sku_code"].isascii()


def test_duplicate_sku_code_returns_40902(client, operator_headers):
    spu = create_spu(client, operator_headers, "SPU-DUP", "重复编码商品")
    create_sku(client, operator_headers, spu["id"], sku_code="FIXED-001")

    again = client.post(
        f"{API}/skus",
        json={"spu_id": spu["id"], "sku_code": "FIXED-001"},
        headers=operator_headers,
    )
    assert again.status_code == 409
    assert again.json()["code"] == 40902


def test_duplicate_barcode_returns_40903(client, operator_headers):
    spu = create_spu(client, operator_headers, "SPU-BC", "条码冲突商品")
    create_sku(client, operator_headers, spu["id"], barcode="6999999900001")

    same_primary = client.post(
        f"{API}/skus",
        json={"spu_id": spu["id"], "barcode": "6999999900001"},
        headers=operator_headers,
    )
    assert same_primary.status_code == 409
    assert same_primary.json()["code"] == 40903

    # An extra barcode on another SKU must not be reusable either.
    other = create_sku(client, operator_headers, spu["id"])
    extra = client.post(
        f"{API}/skus/{other['id']}/barcodes",
        json={"barcode": "6999999900001"},
        headers=operator_headers,
    )
    assert extra.status_code == 409
    assert extra.json()["code"] == 40903


def test_new_sku_gets_a_zero_stock_row_in_every_active_warehouse(
    client, operator_headers, owner_headers
):
    warehouse_a = create_warehouse(client, owner_headers, name="仓 A", code="WH-A")
    warehouse_b = create_warehouse(client, owner_headers, name="仓 B", code="WH-B")
    spu = create_spu(client, operator_headers, "SPU-STOCK", "铺货商品")
    sku = create_sku(client, operator_headers, spu["id"], safety_qty=4)

    rows = client.get(
        f"{API}/inventory?sku_id={sku['id']}&page_size=200", headers=operator_headers
    ).json()["items"]
    by_warehouse = {row["warehouse_id"]: row for row in rows}

    assert warehouse_a["id"] in by_warehouse
    assert warehouse_b["id"] in by_warehouse
    for row in by_warehouse.values():
        assert row["on_hand_qty"] == 0
        assert row["reserved_qty"] == 0
        assert row["safety_qty"] == 4
        # 可售 = 实际 - 已占用 - 安全
        assert row["available_qty"] == 0 - 0 - 4


def test_safety_stock_change_flows_into_existing_stock_rows(
    client, operator_headers, owner_headers
):
    create_warehouse(client, owner_headers, name="安全库存仓", code="WH-SAFE")
    spu = create_spu(client, operator_headers, "SPU-SAFE", "安全库存商品")
    sku = create_sku(client, operator_headers, spu["id"], safety_qty=1)

    client.patch(f"{API}/skus/{sku['id']}", json={"safety_qty": 7}, headers=operator_headers)

    rows = client.get(f"{API}/inventory?sku_id={sku['id']}", headers=operator_headers).json()["items"]
    assert rows and all(row["safety_qty"] == 7 for row in rows)


def test_resolve_sku_by_barcode(client, operator_headers):
    spu = create_spu(client, operator_headers, "SPU-SCAN", "扫码商品")
    sku = create_sku(client, operator_headers, spu["id"], barcode="690000009001")

    found = client.get(f"{API}/skus/resolve?barcode=690000009001", headers=operator_headers)
    assert found.status_code == 200
    assert found.json()["id"] == sku["id"]

    missing = client.get(f"{API}/skus/resolve?barcode=000000000000", headers=operator_headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == 40411


def test_resolve_finds_an_extra_barcode(client, operator_headers):
    spu = create_spu(client, operator_headers, "SPU-SCAN2", "附加条码商品")
    sku = create_sku(client, operator_headers, spu["id"])
    client.post(
        f"{API}/skus/{sku['id']}/barcodes",
        json={"barcode": "690000009777", "remark": "备用条码"},
        headers=operator_headers,
    )

    found = client.get(f"{API}/skus/resolve?barcode=690000009777", headers=operator_headers)
    assert found.status_code == 200
    assert found.json()["id"] == sku["id"]

    listed = client.get(f"{API}/skus/{sku['id']}/barcodes", headers=operator_headers).json()
    assert len(listed) == 1
    removed = client.delete(
        f"{API}/skus/{sku['id']}/barcodes/{listed[0]['id']}", headers=operator_headers
    )
    assert removed.status_code == 204
    assert client.get(f"{API}/skus/{sku['id']}/barcodes", headers=operator_headers).json() == []


def test_missing_sku_and_spu_return_404(client, operator_headers):
    assert client.get(f"{API}/spus/987654", headers=operator_headers).json()["code"] == 40410
    assert client.get(f"{API}/skus/987654", headers=operator_headers).json()["code"] == 40411


def test_spu_and_sku_listing_supports_filters(client, operator_headers):
    spu = create_spu(client, operator_headers, "SPU-FILTER", "筛选商品")
    create_sku(client, operator_headers, spu["id"], spec_json={"size": "L"})

    listed = client.get(f"{API}/spus?keyword=SPU-FILTER", headers=operator_headers).json()
    assert listed["total"] == 1

    by_spu = client.get(f"{API}/skus?spu_id={spu['id']}", headers=operator_headers).json()
    assert by_spu["total"] == 1
    assert by_spu["items"][0]["spu_id"] == spu["id"]

    none = client.get(f"{API}/skus?keyword=绝对不存在的关键字", headers=operator_headers).json()
    assert none["total"] == 0


def test_archiving_a_sku_is_a_soft_state_change(client, operator_headers):
    spu = create_spu(client, operator_headers, "SPU-ARCH", "归档商品")
    sku = create_sku(client, operator_headers, spu["id"])

    updated = client.patch(
        f"{API}/skus/{sku['id']}", json={"status": "archived"}, headers=operator_headers
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "archived"
    # Still retrievable, so historical ledger rows keep resolving.
    assert client.get(f"{API}/skus/{sku['id']}", headers=operator_headers).status_code == 200
