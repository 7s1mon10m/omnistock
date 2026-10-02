"""CSV 导出与审计日志。

导出要证明两件事：**Excel 打开不是乱码**，以及**超限会明确报错而不是悄悄
截断** —— 截断会让报表说谎，比报错危险得多。

审计要证明的是：写操作一定留痕，且留痕本身不可改。
"""

from __future__ import annotations

import pytest

from conftest import (
    API,
    adjust_stock,
    create_channel,
    create_sku,
    create_spu,
    create_warehouse,
    uniq,
)


@pytest.fixture()
def warehouse(client, owner_headers):
    tag = uniq("EXP")
    return create_warehouse(client, owner_headers, name=f"导出仓{tag}", code=f"WH-{tag}")


# ------------------------------------------------------------------ 导出
def test_the_csv_starts_with_a_bom_and_chinese_headers(client, owner_headers, warehouse):
    response = client.get("/api/v1/exports/sku-stock.csv", headers=owner_headers)
    assert response.status_code == 200

    raw = response.content
    # BOM 是 Excel 在中文 Windows 上正确识别 UTF-8 的唯一可靠方式
    assert raw[:3] == b"\xef\xbb\xbf", "缺少 UTF-8 BOM，Excel 打开会是乱码"

    text = raw.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("SKU编码")


def test_a_chinese_filename_is_encoded_for_the_header(client, owner_headers, warehouse):
    """HTTP 头只支持 latin-1，中文文件名必须用 RFC 5987 的 filename*。"""
    response = client.get("/api/v1/exports/sku-stock.csv", headers=owner_headers)
    disposition = response.headers["content-disposition"]
    assert "filename*=" in disposition, "没有 filename*，中文文件名会变成转义串"


def test_every_report_can_be_exported(client, owner_headers, warehouse):
    for name in (
        "sku-stock",
        "turnover",
        "supplier-ontime",
        "channel-sales",
        "stockout",
        "return-rate",
        "slow-moving",
        "purchase-amount",
        "stocktake-variance",
        "low-stock",
    ):
        response = client.get(f"/api/v1/exports/{name}.csv", headers=owner_headers)
        assert response.status_code == 200, f"{name} 导出失败：{response.text[:200]}"
        assert response.content[:3] == b"\xef\xbb\xbf", f"{name} 缺少 BOM"


def test_an_unknown_report_name_is_refused(client, owner_headers, warehouse):
    response = client.get("/api/v1/exports/nope.csv", headers=owner_headers)
    assert response.status_code == 404
    assert response.json()["code"] == 40071


def test_exporting_more_than_the_limit_is_refused(client, owner_headers, warehouse, monkeypatch):
    """超限时报错，而不是悄悄截断 —— 截断的报表比报错危险。"""
    from app.core.config import settings

    spu = create_spu(client, owner_headers, f"SPU-{uniq('L')}", "超限商品")
    sku = create_sku(client, owner_headers, spu["id"], sku_code=f"SKU-{uniq('L')}")
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 5, "备货")

    # 先确认不超限能正常导出，再把上限压到 0 验证它会拒绝
    assert client.get("/api/v1/exports/sku-stock.csv", headers=owner_headers).status_code == 200

    monkeypatch.setattr(settings, "EXPORT_MAX_ROWS", 0)
    response = client.get("/api/v1/exports/sku-stock.csv", headers=owner_headers)
    assert response.status_code == 400
    assert response.json()["code"] == 40070


def test_amounts_are_exported_in_yuan_not_cents(client, owner_headers, warehouse):
    spu = create_spu(client, owner_headers, f"SPU-{uniq('Y')}", "金额商品")
    sku = create_sku(
        client, owner_headers, spu["id"], sku_code=f"SKU-{uniq('Y')}", purchase_price_cents=1234
    )
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 2, "备货")

    text = client.get("/api/v1/exports/sku-stock.csv", headers=owner_headers).content.decode(
        "utf-8-sig"
    )
    assert "24.68" in text, "金额应以元导出（2 × 12.34）"


# ------------------------------------------------------------------ 审计
def test_a_write_operation_is_audited(client, owner_headers, warehouse):
    tag = uniq("AUD")
    spu = create_spu(client, owner_headers, f"SPU-{tag}", "审计商品")
    sku = create_sku(client, owner_headers, spu["id"], sku_code=f"SKU-{tag}")
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 7, "审计测试")

    logs = client.get(f"{API}/audit-logs?page_size=100", headers=owner_headers).json()
    actions = {row["action"] for row in logs["items"]}
    assert "inventory.adjust" in actions, f"库存调整必须留痕，实际：{sorted(actions)}"


def test_the_audit_entry_names_the_actor(client, owner_headers, warehouse):
    logs = client.get(f"{API}/audit-logs?page_size=100", headers=owner_headers).json()
    entry = next(row for row in logs["items"] if row["action"] == "warehouses.post")
    # 用户名冗余存下来：用户以后改名，历史记录仍要能读懂「当时是谁干的」
    assert entry["actor_name"], "审计记录必须留下操作人名字"
    assert entry["status_code"] == 201
    assert entry["path"]


def test_audit_logs_can_be_searched_by_action(client, owner_headers, warehouse):
    logs = client.get(f"{API}/audit-logs?action=warehouses", headers=owner_headers).json()
    assert logs["total"] >= 1
    assert all("warehouses" in row["action"] for row in logs["items"])


def test_audit_logs_can_be_searched_by_actor(client, owner_headers, warehouse):
    logs = client.get(f"{API}/audit-logs?actor=owner01", headers=owner_headers).json()
    assert logs["total"] >= 1


def test_a_failed_write_is_not_audited(client, owner_headers, warehouse):
    """被拒绝的操作什么都没改，不该污染审计流。"""
    before = client.get(f"{API}/audit-logs?page_size=200", headers=owner_headers).json()["total"]
    # 缺 reason 会被拒绝
    client.post(
        f"{API}/inventory/adjust",
        json={"sku_id": 999999, "warehouse_id": warehouse["id"], "qty_delta": 1, "reason": ""},
        headers=owner_headers,
    )
    after = client.get(f"{API}/audit-logs?page_size=200", headers=owner_headers).json()["total"]
    assert after == before


def test_audit_logs_are_read_only(client, owner_headers, warehouse):
    """审计表一旦可改，就不再是审计。"""
    assert client.put(f"{API}/audit-logs", json={}, headers=owner_headers).status_code == 405
    assert client.delete(f"{API}/audit-logs", headers=owner_headers).status_code == 405


def test_only_an_admin_may_read_audit_logs(client, owner_headers, operator_headers, warehouse):
    assert client.get(f"{API}/audit-logs", headers=operator_headers).status_code == 403
    assert client.get(f"{API}/audit-logs", headers=owner_headers).status_code == 200


def test_login_is_not_written_to_the_audit_log(client, owner_headers):
    """登录有自己的链路，且 token 不该落进一张可查询的表。"""
    logs = client.get(f"{API}/audit-logs?page_size=200", headers=owner_headers).json()
    assert [row for row in logs["items"] if "auth" in row["action"]] == []
