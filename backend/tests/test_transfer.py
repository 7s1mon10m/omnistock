"""M5 多仓库调拨。

整个里程碑的成败取决于一件事：**在途是否被显式建模**。下面的用例反复验证
同一条不变量 —— 货在路上的时候，两个仓库的可售都不该包含它，实际库存也不能
重复计算。
"""

from __future__ import annotations

import pytest

from conftest import (
    API,
    adjust_stock,
    approve_transfer,
    create_sku,
    create_spu,
    create_transfer,
    get_transfer,
    inventory_row,
    inventory_row_or_zero,
    receive_transfer,
    ship_transfer,
    uniq,
)


@pytest.fixture()
def two_warehouses(client, owner_headers, catalog):
    """A source warehouse with stock and a destination warehouse with none."""
    tag = uniq("TR")
    spu = create_spu(client, owner_headers, f"SPU-{tag}", "调拨测试商品")
    sku = create_sku(client, owner_headers, spu["id"], sku_code=f"SKU-{tag}", safety_qty=0)

    source = catalog["warehouse"]
    adjust_stock(client, catalog["headers"], sku["id"], source["id"], 100, "备货")

    from conftest import create_warehouse

    target = create_warehouse(
        client, owner_headers, name=f"调入仓{tag}", code=f"WH-T-{tag}", type_="live"
    )

    def start(quantity: int, reason: str = "直播备货") -> dict:
        response = create_transfer(
            client,
            owner_headers,
            source["id"],
            target["id"],
            [{"sku_id": sku["id"], "quantity": quantity}],
            reason=reason,
        )
        assert response.status_code == 201, response.text
        return response.json()

    return {
        "sku": sku,
        "source": source,
        "target": target,
        "start": start,
        "catalog": catalog,
    }


def _src(client, headers, fixture) -> dict:
    # 调入仓在收货前在库存表里根本没有行，零值和"没有行"在这里是同义的。
    return inventory_row_or_zero(client, headers, fixture["sku"]["id"], fixture["source"]["id"])


def _dst(client, headers, fixture) -> dict:
    return inventory_row_or_zero(client, headers, fixture["sku"]["id"], fixture["target"]["id"])


# --------------------------------------------------------------------- create
def test_a_new_transfer_waits_for_approval(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](30)
    assert transfer["status"] == "pending"
    assert transfer["transfer_no"].startswith("TR")
    assert transfer["total_quantity"] == 30
    assert transfer["requested_by_name"]

    # 申请本身不动库存
    assert _src(client, owner_headers, two_warehouses)["on_hand_qty"] == 100


def test_shipping_to_the_same_warehouse_is_rejected(client, owner_headers, two_warehouses):
    response = create_transfer(
        client,
        owner_headers,
        two_warehouses["source"]["id"],
        two_warehouses["source"]["id"],
        [{"sku_id": two_warehouses["sku"]["id"], "quantity": 1}],
    )
    assert response.status_code == 422


def test_an_empty_transfer_is_rejected(client, owner_headers, two_warehouses):
    response = create_transfer(
        client, owner_headers, two_warehouses["source"]["id"], two_warehouses["target"]["id"], []
    )
    assert response.status_code == 422


# ------------------------------------------------------------------- approval
def test_approval_moves_nothing_but_changes_the_state(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](20)
    approved = approve_transfer(client, owner_headers, transfer["id"])
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_by_name"]

    assert _src(client, owner_headers, two_warehouses)["on_hand_qty"] == 100
    assert _dst(client, owner_headers, two_warehouses)["on_hand_qty"] == 0


def test_approving_twice_is_refused(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](20)
    approve_transfer(client, owner_headers, transfer["id"])

    again = approve_transfer(client, owner_headers, transfer["id"])
    assert again.status_code == 409
    assert again.json()["code"] == 40951


def test_rejecting_leaves_stock_untouched(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](20)
    rejected = client.post(
        f"{API}/transfers/{transfer['id']}/reject",
        json={"reason": "本月预算不够"},
        headers=owner_headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["reject_reason"] == "本月预算不够"

    assert _src(client, owner_headers, two_warehouses)["on_hand_qty"] == 100
    assert _dst(client, owner_headers, two_warehouses)["on_hand_qty"] == 0


def test_shipping_without_approval_is_refused(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](20)
    response = ship_transfer(client, owner_headers, transfer["id"])
    assert response.status_code == 409
    assert response.json()["code"] == 40951


# ----------------------------------------------------------------------- ship
def test_shipping_moves_stock_into_in_transit(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](30)
    approve_transfer(client, owner_headers, transfer["id"])

    shipped = ship_transfer(client, owner_headers, transfer["id"])
    assert shipped.status_code == 200, shipped.text
    assert shipped.json()["status"] == "in_transit"

    source = _src(client, owner_headers, two_warehouses)
    target = _dst(client, owner_headers, two_warehouses)
    assert source["on_hand_qty"] == 70, "调出仓实际库存应减少"
    assert source["in_transit_qty"] == 0
    assert target["in_transit_qty"] == 30, "在途记在调入仓"
    assert target["on_hand_qty"] == 0, "还没收到，实际库存不该有"


def test_in_transit_is_not_sellable(client, owner_headers, two_warehouses):
    """最核心的一条：在途不能算可售。"""
    transfer = two_warehouses["start"](30)
    approve_transfer(client, owner_headers, transfer["id"])
    ship_transfer(client, owner_headers, transfer["id"])

    target = _dst(client, owner_headers, two_warehouses)
    assert target["in_transit_qty"] == 30
    assert target["available_qty"] == 0, "在途货不能被卖出去"

    # 两边加起来仍然是发出前的总量，没有凭空多也没有凭空少
    total = (
        _src(client, owner_headers, two_warehouses)["on_hand_qty"]
        + target["on_hand_qty"]
        + target["in_transit_qty"]
    )
    assert total == 100


def test_shipping_more_than_available_is_refused(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](100)
    approve_transfer(client, owner_headers, transfer["id"])

    # 先把源仓的可售吃掉一半
    client.post(
        f"{API}/inventory/reserve",
        json={
            "sku_id": two_warehouses["sku"]["id"],
            "warehouse_id": two_warehouses["source"]["id"],
            "quantity": 60,
        },
        headers=owner_headers,
    )

    response = ship_transfer(client, owner_headers, transfer["id"])
    assert response.status_code == 409
    assert response.json()["code"] == 40952
    shortages = response.json()["detail"]["shortages"]
    assert shortages[0]["available"] == 40

    # 整单不发：源仓实际库存和调入仓在途都没动
    assert _src(client, owner_headers, two_warehouses)["on_hand_qty"] == 100
    assert _dst(client, owner_headers, two_warehouses)["in_transit_qty"] == 0


def test_shipping_less_than_requested_is_allowed(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](30)
    approve_transfer(client, owner_headers, transfer["id"])

    item_id = transfer["items"][0]["id"]
    shipped = ship_transfer(
        client, owner_headers, transfer["id"], [{"transfer_item_id": item_id, "quantity": 12}]
    )
    assert shipped.status_code == 200
    assert shipped.json()["shipped_quantity"] == 12
    assert _src(client, owner_headers, two_warehouses)["on_hand_qty"] == 88


def test_shipping_more_than_requested_is_refused(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](30)
    approve_transfer(client, owner_headers, transfer["id"])

    item_id = transfer["items"][0]["id"]
    response = ship_transfer(
        client, owner_headers, transfer["id"], [{"transfer_item_id": item_id, "quantity": 50}]
    )
    assert response.status_code == 409
    assert response.json()["code"] == 40953


# -------------------------------------------------------------------- receive
def test_receiving_turns_in_transit_into_stock(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](30)
    approve_transfer(client, owner_headers, transfer["id"])
    ship_transfer(client, owner_headers, transfer["id"])

    received = receive_transfer(client, owner_headers, transfer["id"], [])
    assert received.status_code == 200, received.text
    assert received.json()["status"] == "received"

    target = _dst(client, owner_headers, two_warehouses)
    assert target["on_hand_qty"] == 30
    assert target["in_transit_qty"] == 0, "收货后在途必须清零"
    assert target["available_qty"] == 30

    assert _src(client, owner_headers, two_warehouses)["on_hand_qty"] == 70


def test_defective_transfer_arrivals_go_to_the_defective_bucket(
    client, owner_headers, two_warehouses
):
    transfer = two_warehouses["start"](30)
    approve_transfer(client, owner_headers, transfer["id"])
    ship_transfer(client, owner_headers, transfer["id"])

    item_id = transfer["items"][0]["id"]
    receive_transfer(
        client,
        owner_headers,
        transfer["id"],
        [{"transfer_item_id": item_id, "quantity": 30, "defective_qty": 2}],
    )

    target = _dst(client, owner_headers, two_warehouses)
    assert target["on_hand_qty"] == 28
    assert target["defective_qty"] == 2
    assert target["in_transit_qty"] == 0
    assert target["available_qty"] == 28, "次品不能进可售"


def test_partial_receipt_keeps_the_rest_in_transit(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](30)
    approve_transfer(client, owner_headers, transfer["id"])
    ship_transfer(client, owner_headers, transfer["id"])

    item_id = transfer["items"][0]["id"]
    first = receive_transfer(
        client, owner_headers, transfer["id"], [{"transfer_item_id": item_id, "quantity": 20}]
    )
    assert first.status_code == 200
    # 没收完就还在途
    assert first.json()["status"] == "in_transit"
    assert first.json()["received_quantity"] == 20

    target = _dst(client, owner_headers, two_warehouses)
    assert target["on_hand_qty"] == 20
    assert target["in_transit_qty"] == 10, "没收的部分仍留在在途"

    second = receive_transfer(
        client, owner_headers, transfer["id"], [{"transfer_item_id": item_id, "quantity": 10}]
    )
    assert second.json()["status"] == "received"
    assert _dst(client, owner_headers, two_warehouses)["in_transit_qty"] == 0


def test_receiving_more_than_shipped_is_refused(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](30)
    approve_transfer(client, owner_headers, transfer["id"])
    ship_transfer(client, owner_headers, transfer["id"])

    item_id = transfer["items"][0]["id"]
    response = receive_transfer(
        client, owner_headers, transfer["id"], [{"transfer_item_id": item_id, "quantity": 40}]
    )
    assert response.status_code == 400
    assert response.json()["code"] == 40041


def test_receiving_before_shipping_is_refused(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](30)
    approve_transfer(client, owner_headers, transfer["id"])

    response = receive_transfer(client, owner_headers, transfer["id"], [])
    assert response.status_code == 409
    assert response.json()["code"] == 40951


# --------------------------------------------------------------------- cancel
def test_a_pending_transfer_can_be_cancelled(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](20)
    response = client.post(
        f"{API}/transfers/{transfer['id']}/cancel", json={"reason": "改主意了"}, headers=owner_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert _src(client, owner_headers, two_warehouses)["on_hand_qty"] == 100


def test_an_in_transit_transfer_cannot_be_cancelled(client, owner_headers, two_warehouses):
    """货一旦上路就必须走完收货 —— 否则在途会变成黑洞。"""
    transfer = two_warehouses["start"](20)
    approve_transfer(client, owner_headers, transfer["id"])
    ship_transfer(client, owner_headers, transfer["id"])

    response = client.post(
        f"{API}/transfers/{transfer['id']}/cancel", json={}, headers=owner_headers
    )
    assert response.status_code == 409
    assert response.json()["code"] == 40951
    assert "必须完成收货" in response.json()["message"]


# ----------------------------------------------------------------------- RBAC
def test_operator_can_request_but_not_approve(
    client, owner_headers, operator_headers, two_warehouses
):
    """运营可以发起调拨，但审批在店主手里 —— 否则很容易把旺销仓搬空。"""
    transfer = two_warehouses["start"](20)
    request_id = transfer["id"]

    denied = approve_transfer(client, operator_headers, request_id)
    assert denied.status_code == 403
    assert denied.json()["code"] == 40301

    assert approve_transfer(client, owner_headers, request_id).status_code == 200


def test_buyer_cannot_ship(client, owner_headers, buyer_headers, two_warehouses):
    transfer = two_warehouses["start"](20)
    approve_transfer(client, owner_headers, transfer["id"])

    denied = ship_transfer(client, buyer_headers, transfer["id"])
    assert denied.status_code == 403
    assert denied.json()["code"] == 40301

    # 但采购可以查看
    assert client.get(f"{API}/transfers", headers=buyer_headers).status_code == 200


# ------------------------------------------------------------------- read views
def test_transfers_can_be_filtered(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](15, reason="大促备货")

    by_status = client.get(
        f"{API}/transfers?status=pending&page_size=200", headers=owner_headers
    ).json()
    assert any(row["id"] == transfer["id"] for row in by_status["items"])

    by_keyword = client.get(
        f"{API}/transfers?keyword={transfer['transfer_no']}", headers=owner_headers
    ).json()
    assert by_keyword["total"] == 1
    assert by_keyword["items"][0]["from_warehouse_code"] == two_warehouses["source"]["code"]
    assert by_keyword["items"][0]["to_warehouse_code"] == two_warehouses["target"]["code"]


def test_an_unknown_transfer_returns_404(client, owner_headers):
    assert client.get(f"{API}/transfers/987654", headers=owner_headers).json()["code"] == 40460


def test_the_ledger_describes_both_sides_of_the_move(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](40)
    approve_transfer(client, owner_headers, transfer["id"])
    ship_transfer(client, owner_headers, transfer["id"])

    ledger = client.get(
        f"{API}/inventory/ledger?sku_id={two_warehouses['sku']['id']}&page_size=200",
        headers=owner_headers,
    ).json()["items"]
    transfers = [row for row in ledger if row["type"] == "transfer_out"]
    assert len(transfers) == 2, "发出会在调出仓与调入仓各写一条流水"

    by_wh = {row["warehouse_id"]: row for row in transfers}
    source = by_wh[two_warehouses["source"]["id"]]
    target = by_wh[two_warehouses["target"]["id"]]

    assert source["qty_delta"] == -40
    assert source["on_hand_before"] + source["qty_delta"] == source["on_hand_after"]
    assert target["qty_delta"] == 0
    assert target["in_transit_before"] == 0
    assert target["in_transit_after"] == 40


def test_receiving_writes_a_single_inbound_row_per_sku(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](25)
    approve_transfer(client, owner_headers, transfer["id"])
    ship_transfer(client, owner_headers, transfer["id"])
    receive_transfer(client, owner_headers, transfer["id"], [])

    ledger = client.get(
        f"{API}/inventory/ledger?sku_id={two_warehouses['sku']['id']}&page_size=200",
        headers=owner_headers,
    ).json()["items"]
    inbound = [row for row in ledger if row["type"] == "transfer_in"]
    assert len(inbound) == 1
    row = inbound[0]
    assert row["warehouse_id"] == two_warehouses["target"]["id"]
    assert row["qty_delta"] == 25
    assert row["in_transit_before"] == 25
    assert row["in_transit_after"] == 0


def test_multi_line_transfer(client, owner_headers, catalog, two_warehouses):
    """一张调拨单可以带多个 SKU，各自独立计量。"""
    tag = uniq("ML")
    spu = create_spu(client, owner_headers, f"SPU-{tag}", "第二件商品")
    second = create_sku(client, owner_headers, spu["id"], sku_code=f"SKU2-{tag}", safety_qty=0)
    adjust_stock(
        client, catalog["headers"], second["id"], two_warehouses["source"]["id"], 60, "备货"
    )

    transfer = create_transfer(
        client,
        owner_headers,
        two_warehouses["source"]["id"],
        two_warehouses["target"]["id"],
        [
            {"sku_id": two_warehouses["sku"]["id"], "quantity": 10},
            {"sku_id": second["id"], "quantity": 25},
        ],
    ).json()
    assert len(transfer["items"]) == 2
    assert transfer["total_quantity"] == 35

    approve_transfer(client, owner_headers, transfer["id"])
    ship_transfer(client, owner_headers, transfer["id"])
    final = receive_transfer(client, owner_headers, transfer["id"], [])
    assert final.json()["status"] == "received"

    assert inventory_row(
        client, owner_headers, second["id"], two_warehouses["target"]["id"]
    )["on_hand_qty"] == 25
    assert _dst(client, owner_headers, two_warehouses)["on_hand_qty"] == 10


def test_get_transfer_returns_the_full_trail(client, owner_headers, two_warehouses):
    transfer = two_warehouses["start"](10)
    approve_transfer(client, owner_headers, transfer["id"])
    ship_transfer(client, owner_headers, transfer["id"])
    receive_transfer(client, owner_headers, transfer["id"], [])

    detail = get_transfer(client, owner_headers, transfer["id"])
    assert detail["status"] == "received"
    assert detail["requested_by_name"]
    assert detail["approved_by_name"]
    assert detail["shipped_by_name"]
    assert detail["received_by_name"]
    assert detail["shipped_at"] is not None
    assert detail["received_at"] is not None
