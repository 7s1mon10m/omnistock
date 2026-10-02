"""盘点差异与审核。

核心不变量只有一条：**未审核的盘点不产生任何库存调整**。

盘盈盘亏会直接改写库存，而库存是所有下游决策的基础。让人手滑输错一个数
就能凭空多出 20 件货，是这个模块绝不能允许的事 —— 所以差异必须有人过目，
且审核通过后要留下操作人、时间与原因。
"""

from __future__ import annotations

import pytest

from conftest import (
    API,
    adjust_stock,
    create_sku,
    create_spu,
    create_warehouse,
    get_stocktake,
    inventory_row_or_zero,
    uniq,
)


@pytest.fixture()
def counted(client, owner_headers):
    """一个仓 + 一个 SKU，账面 30 件。"""
    tag = uniq("ST")
    warehouse = create_warehouse(client, owner_headers, name=f"盘点仓{tag}", code=f"WH-{tag}")
    spu = create_spu(client, owner_headers, f"SPU-{tag}", "盘点商品")
    sku = create_sku(
        client,
        owner_headers,
        spu["id"],
        sku_code=f"SKU-{tag}",
        barcode=f"SB{tag}",
        safety_qty=0,
    )
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 30, "备货")
    return {
        "warehouse": warehouse,
        "sku": sku,
        "headers": owner_headers,
        "tag": tag,
    }


def open_stocktake(client, headers, fixture, **extra):
    from conftest import create_stocktake

    response = create_stocktake(client, headers, fixture["warehouse"]["id"], **extra)
    assert response.status_code == 201, response.text
    return response.json()


def line_of(body, sku_id: int) -> dict:
    return next(row for row in body["items"] if row["sku_id"] == sku_id)


def submit(client, headers, stocktake_id: int):
    response = client.post(f"{API}/stocktakes/{stocktake_id}/submit", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def approve(client, headers, stocktake_id: int, **extra):
    return client.post(
        f"{API}/stocktakes/{stocktake_id}/approve", json=extra, headers=headers
    )


# ------------------------------------------------------------------ 建单
def test_a_stocktake_freezes_the_book_quantity(client, owner_headers, counted):
    body = open_stocktake(client, owner_headers, counted)
    line = line_of(body, counted["sku"]["id"])
    assert line["book_qty"] == 30
    assert line["counted_qty"] is None, "还没盘，实盘数为空而不是 0"


def test_only_the_requested_skus_are_listed(client, owner_headers, counted):
    body = open_stocktake(client, owner_headers, counted, sku_ids=[counted["sku"]["id"]])
    assert [row["sku_id"] for row in body["items"]] == [counted["sku"]["id"]]


# ------------------------------------------------------------------ 录入
def test_counting_records_the_variance(client, owner_headers, counted):
    body = open_stocktake(client, owner_headers, counted)
    line = line_of(body, counted["sku"]["id"])

    from conftest import count_stocktake

    updated = count_stocktake(
        client,
        owner_headers,
        body["id"],
        [{"stocktake_item_id": line["id"], "counted_qty": 26, "reason": "少了 4 件"}],
    ).json()
    assert updated["total_variance"] == -4
    assert line_of(updated, counted["sku"]["id"])["variance_qty"] == -4


def test_scanning_a_barcode_finds_the_line(client, owner_headers, counted):
    body = open_stocktake(client, owner_headers, counted)
    response = client.post(
        f"{API}/stocktakes/{body['id']}/scan",
        json={"barcode": counted["sku"]["barcode"], "counted_qty": 29},
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    assert line_of(response.json(), counted["sku"]["id"])["counted_qty"] == 29


def test_scanning_an_unknown_barcode_is_rejected(client, owner_headers, counted):
    body = open_stocktake(client, owner_headers, counted)
    response = client.post(
        f"{API}/stocktakes/{body['id']}/scan",
        json={"barcode": "NOT-A-BARCODE", "counted_qty": 1},
        headers=owner_headers,
    )
    assert response.status_code == 404


def test_recounting_takes_the_latest_number(client, owner_headers, counted):
    from conftest import count_stocktake

    body = open_stocktake(client, owner_headers, counted)
    line = line_of(body, counted["sku"]["id"])
    count_stocktake(
        client, owner_headers, body["id"], [{"stocktake_item_id": line["id"], "counted_qty": 20}]
    )
    updated = count_stocktake(
        client, owner_headers, body["id"], [{"stocktake_item_id": line["id"], "counted_qty": 28}]
    ).json()
    assert line_of(updated, counted["sku"]["id"])["counted_qty"] == 28


def test_submitting_without_any_count_is_refused(client, owner_headers, counted):
    body = open_stocktake(client, owner_headers, counted)
    response = client.post(f"{API}/stocktakes/{body['id']}/submit", headers=owner_headers)
    assert response.status_code == 400


# ------------------------------------------------------- 未审核不动库存
def test_a_submitted_stocktake_does_not_touch_inventory(client, owner_headers, counted):
    """提交不等于落账。这一条是盘点模块的底线。"""
    from conftest import count_stocktake

    before = inventory_row_or_zero(
        client, owner_headers, counted["sku"]["id"], counted["warehouse"]["id"]
    )

    body = open_stocktake(client, owner_headers, counted)
    line = line_of(body, counted["sku"]["id"])
    count_stocktake(
        client, owner_headers, body["id"], [{"stocktake_item_id": line["id"], "counted_qty": 20}]
    )
    assert submit(client, owner_headers, body["id"])["status"] == "submitted"

    after = inventory_row_or_zero(
        client, owner_headers, counted["sku"]["id"], counted["warehouse"]["id"]
    )
    assert after["on_hand_qty"] == before["on_hand_qty"], "提交阶段绝不能改库存"


def test_approval_writes_the_adjustment(client, owner_headers, counted):
    from conftest import count_stocktake

    before = inventory_row_or_zero(
        client, owner_headers, counted["sku"]["id"], counted["warehouse"]["id"]
    )
    body = open_stocktake(client, owner_headers, counted)
    line = line_of(body, counted["sku"]["id"])
    count_stocktake(
        client,
        owner_headers,
        body["id"],
        [{"stocktake_item_id": line["id"], "counted_qty": 20, "reason": "盘亏 10"}],
    )
    submit(client, owner_headers, body["id"])

    response = approve(client, owner_headers, body["id"], remark="同意调整")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"

    after = inventory_row_or_zero(
        client, owner_headers, counted["sku"]["id"], counted["warehouse"]["id"]
    )
    assert after["on_hand_qty"] == before["on_hand_qty"] - 10

    ledger = client.get(
        f"{API}/inventory/ledger?sku_id={counted['sku']['id']}&page_size=100",
        headers=owner_headers,
    ).json()["items"]
    mine = [row for row in ledger if row["ref_type"] == "stocktake"]
    assert len(mine) == 1
    assert mine[0]["type"] == "stocktake_adjust"
    assert mine[0]["qty_delta"] == -10
    assert mine[0]["operator_name"], "调整必须留下操作人"


def test_a_gain_raises_stock(client, owner_headers, counted):
    from conftest import count_stocktake

    before = inventory_row_or_zero(
        client, owner_headers, counted["sku"]["id"], counted["warehouse"]["id"]
    )
    body = open_stocktake(client, owner_headers, counted)
    line = line_of(body, counted["sku"]["id"])
    count_stocktake(
        client, owner_headers, body["id"], [{"stocktake_item_id": line["id"], "counted_qty": 35}]
    )
    submit(client, owner_headers, body["id"])
    approve(client, owner_headers, body["id"])

    after = inventory_row_or_zero(
        client, owner_headers, counted["sku"]["id"], counted["warehouse"]["id"]
    )
    assert after["on_hand_qty"] == before["on_hand_qty"] + 5


def test_a_no_variance_stocktake_writes_nothing(client, owner_headers, counted):
    from conftest import count_stocktake

    body = open_stocktake(client, owner_headers, counted)
    line = line_of(body, counted["sku"]["id"])
    count_stocktake(
        client, owner_headers, body["id"], [{"stocktake_item_id": line["id"], "counted_qty": 30}]
    )
    submit(client, owner_headers, body["id"])
    approve(client, owner_headers, body["id"])

    ledger = client.get(
        f"{API}/inventory/ledger?sku_id={counted['sku']['id']}&page_size=100",
        headers=owner_headers,
    ).json()["items"]
    assert [row for row in ledger if row["ref_type"] == "stocktake"] == []


# ------------------------------------------------------------------ 状态机
def test_approving_twice_is_refused(client, owner_headers, counted):
    from conftest import count_stocktake

    body = open_stocktake(client, owner_headers, counted)
    line = line_of(body, counted["sku"]["id"])
    count_stocktake(
        client, owner_headers, body["id"], [{"stocktake_item_id": line["id"], "counted_qty": 25}]
    )
    submit(client, owner_headers, body["id"])
    assert approve(client, owner_headers, body["id"]).status_code == 200

    again = approve(client, owner_headers, body["id"])
    assert again.status_code == 409
    assert again.json()["code"] == 40981


def test_approving_before_submitting_is_refused(client, owner_headers, counted):
    from conftest import count_stocktake

    body = open_stocktake(client, owner_headers, counted)
    line = line_of(body, counted["sku"]["id"])
    count_stocktake(
        client, owner_headers, body["id"], [{"stocktake_item_id": line["id"], "counted_qty": 25}]
    )
    response = approve(client, owner_headers, body["id"])
    assert response.status_code == 409
    assert response.json()["code"] == 40983


def test_an_approved_stocktake_cannot_be_cancelled(client, owner_headers, counted):
    from conftest import count_stocktake

    body = open_stocktake(client, owner_headers, counted)
    line = line_of(body, counted["sku"]["id"])
    count_stocktake(
        client, owner_headers, body["id"], [{"stocktake_item_id": line["id"], "counted_qty": 30}]
    )
    submit(client, owner_headers, body["id"])
    approve(client, owner_headers, body["id"])

    response = client.post(
        f"{API}/stocktakes/{body['id']}/cancel", json={"reason": "反悔"}, headers=owner_headers
    )
    assert response.status_code == 409


def test_counting_after_submission_is_refused(client, owner_headers, counted):
    from conftest import count_stocktake

    body = open_stocktake(client, owner_headers, counted)
    line = line_of(body, counted["sku"]["id"])
    count_stocktake(
        client, owner_headers, body["id"], [{"stocktake_item_id": line["id"], "counted_qty": 25}]
    )
    submit(client, owner_headers, body["id"])

    response = count_stocktake(
        client, owner_headers, body["id"], [{"stocktake_item_id": line["id"], "counted_qty": 10}]
    )
    assert response.status_code == 409


# ------------------------------------------------------------------ 权限
def test_only_an_admin_may_approve(client, owner_headers, counted, warehouse_headers):
    from conftest import count_stocktake

    body = open_stocktake(client, warehouse_headers, counted)
    line = line_of(body, counted["sku"]["id"])
    count_stocktake(
        client, warehouse_headers, body["id"], [{"stocktake_item_id": line["id"], "counted_qty": 25}]
    )
    submit(client, warehouse_headers, body["id"])

    # 仓管能盘能提交，但拍板定案的必须是店主/管理员
    assert approve(client, warehouse_headers, body["id"]).status_code == 403
    assert approve(client, owner_headers, body["id"]).status_code == 200
