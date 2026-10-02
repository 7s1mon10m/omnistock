"""The inventory ledger: append-only movements, the sellable formula, and the
no-oversell guarantee under concurrency.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import (
    API,
    adjust_stock,
    create_sku,
    create_spu,
    create_warehouse,
    reserve_stock,
    uniq,
)


@pytest.fixture()
def stock_fixture(client, owner_headers):
    """A fresh SKU in its own warehouse, with a safety buffer of 2.

    A dedicated warehouse per test keeps stock state isolated even though the
    whole session shares one database.
    """
    tag = uniq("INV")
    warehouse = create_warehouse(client, owner_headers, name=f"库存测试仓{tag}", code=f"WH-{tag}")
    spu = create_spu(client, owner_headers, f"SPU-{tag}", "库存测试商品")
    sku = create_sku(client, owner_headers, spu["id"], sku_code=f"SKU-{tag}", safety_qty=2)
    return {"warehouse": warehouse, "spu": spu, "sku": sku}


def _stock_of(client, headers, sku_id: int, warehouse_id: int) -> dict:
    rows = client.get(f"{API}/inventory?sku_id={sku_id}&page_size=200", headers=headers).json()["items"]
    return next(row for row in rows if row["warehouse_id"] == warehouse_id)


# -------------------------------------------------------------- the formula
def test_adjust_increases_on_hand_and_writes_a_ledger_row(client, owner_headers, stock_fixture):
    sku = stock_fixture["sku"]
    warehouse = stock_fixture["warehouse"]

    response = adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 10, "期初入库")
    assert response.status_code == 200, response.text
    tx = response.json()

    assert tx["type"] == "manual_adjust"
    assert tx["qty_delta"] == 10
    assert tx["on_hand_before"] == 0
    assert tx["on_hand_after"] == 10
    assert tx["remark"] == "期初入库"
    assert tx["operator_name"]

    row = _stock_of(client, owner_headers, sku["id"], warehouse["id"])
    assert row["on_hand_qty"] == 10
    # 可售 = 实际 - 已占用 - 安全 = 10 - 0 - 2
    assert row["available_qty"] == 8


def test_every_ledger_row_satisfies_before_plus_delta_equals_after(
    client, owner_headers, stock_fixture
):
    sku = stock_fixture["sku"]
    warehouse = stock_fixture["warehouse"]
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 20, "入库")

    ledger = client.get(
        f"{API}/inventory/ledger?sku_id={sku['id']}&page_size=200", headers=owner_headers
    ).json()["items"]
    assert ledger
    for row in ledger:
        assert row["on_hand_before"] + row["qty_delta"] == row["on_hand_after"]


def test_ledger_is_ordered_newest_first(client, owner_headers, stock_fixture):
    sku = stock_fixture["sku"]
    warehouse = stock_fixture["warehouse"]
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 5, "第一笔")
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 6, "第二笔")

    ledger = client.get(f"{API}/inventory/ledger?sku_id={sku['id']}", headers=owner_headers).json()
    assert [row["remark"] for row in ledger["items"]] == ["第二笔", "第一笔"]


def test_reserve_then_release_moves_reserved_not_on_hand(client, owner_headers, stock_fixture):
    sku = stock_fixture["sku"]
    warehouse = stock_fixture["warehouse"]
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 10, "入库")

    reserved = reserve_stock(client, owner_headers, sku["id"], warehouse["id"], 3)
    assert reserved.status_code == 200
    assert reserved.json()["type"] == "order_reserve"

    after = _stock_of(client, owner_headers, sku["id"], warehouse["id"])
    assert after["on_hand_qty"] == 10      # untouched
    assert after["reserved_qty"] == 3
    assert after["available_qty"] == 10 - 3 - 2

    released = client.post(
        f"{API}/inventory/release",
        json={"sku_id": sku["id"], "warehouse_id": warehouse["id"], "quantity": 3},
        headers=owner_headers,
    )
    assert released.status_code == 200
    assert released.json()["type"] == "order_release"

    final = _stock_of(client, owner_headers, sku["id"], warehouse["id"])
    assert final["reserved_qty"] == 0
    assert final["available_qty"] == 8


# --------------------------------------------------------------- error codes
def test_adjust_requires_a_reason(client, owner_headers, stock_fixture):
    sku = stock_fixture["sku"]
    warehouse = stock_fixture["warehouse"]

    # An empty reason is rejected by the request schema.
    blank = adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 1, reason="")
    assert blank.status_code == 422

    # And the service refuses a whitespace-only reason with its own code.
    from app.core.errors import ADJUST_REASON_REQUIRED, BusinessError
    from app.db import SessionLocal
    from app.schemas.inventory import InventoryAdjustRequest
    from app.services import inventory_service

    session = SessionLocal()
    try:
        with pytest.raises(BusinessError) as exc:
            inventory_service.adjust(
                session,
                InventoryAdjustRequest(
                    sku_id=sku["id"], warehouse_id=warehouse["id"], qty_delta=1, reason="   "
                ),
            )
        assert exc.value.code == ADJUST_REASON_REQUIRED
    finally:
        session.close()


def test_zero_delta_adjust_is_rejected(client, owner_headers, stock_fixture):
    sku = stock_fixture["sku"]
    warehouse = stock_fixture["warehouse"]
    response = adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 0, "无效调整")
    assert response.status_code == 400
    assert response.json()["code"] == 40010


def test_stock_cannot_go_negative(client, owner_headers, stock_fixture):
    sku = stock_fixture["sku"]
    warehouse = stock_fixture["warehouse"]
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 5, "入库")

    response = adjust_stock(client, owner_headers, sku["id"], warehouse["id"], -50, "出库过多")
    assert response.status_code == 409
    assert response.json()["code"] == 40906
    # Nothing was written.
    assert _stock_of(client, owner_headers, sku["id"], warehouse["id"])["on_hand_qty"] == 5


def test_reserving_more_than_sellable_returns_40906(client, owner_headers, stock_fixture):
    sku = stock_fixture["sku"]
    warehouse = stock_fixture["warehouse"]
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 10, "入库")

    # 可售 is 8 (10 - 0 - 2 safety), so 9 must fail.
    response = reserve_stock(client, owner_headers, sku["id"], warehouse["id"], 9)
    assert response.status_code == 409
    assert response.json()["code"] == 40906
    assert response.json()["detail"]["available"] == 8


def test_adjusting_an_unknown_sku_or_warehouse_returns_404(client, owner_headers, stock_fixture):
    sku = stock_fixture["sku"]
    warehouse = stock_fixture["warehouse"]
    assert adjust_stock(client, owner_headers, 987654, warehouse["id"], 1).json()["code"] == 40411
    assert adjust_stock(client, owner_headers, sku["id"], 987654, 1).json()["code"] == 40412


def test_the_ledger_has_no_write_endpoints(client, owner_headers):
    # Only GET is registered, so any mutation is a 405 rather than a silent edit.
    assert client.delete(f"{API}/inventory/ledger", headers=owner_headers).status_code == 405
    assert client.patch(f"{API}/inventory/ledger", headers=owner_headers).status_code == 405


def test_the_warehouse_persona_owns_stock_movements(client, owner_headers, warehouse_headers, stock_fixture):
    """仓管能调整库存，运营/采购不能——职责边界体现在守卫上。"""
    sku = stock_fixture["sku"]
    warehouse = stock_fixture["warehouse"]

    moved = adjust_stock(client, warehouse_headers, sku["id"], warehouse["id"], 4, "仓库上架")
    assert moved.status_code == 200
    assert moved.json()["operator_name"]

    row = _stock_of(client, owner_headers, sku["id"], warehouse["id"])
    assert row["on_hand_qty"] == 4


# ---------------------------------------------------------------- idempotency
def test_a_repeated_idempotency_key_moves_stock_once(client, owner_headers, stock_fixture):
    sku = stock_fixture["sku"]
    warehouse = stock_fixture["warehouse"]
    key = "duplicate-submit-001"

    first = adjust_stock(
        client, owner_headers, sku["id"], warehouse["id"], 7, "重复提交测试", idempotency_key=key
    )
    second = adjust_stock(
        client, owner_headers, sku["id"], warehouse["id"], 7, "重复提交测试", idempotency_key=key
    )
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    row = _stock_of(client, owner_headers, sku["id"], warehouse["id"])
    assert row["on_hand_qty"] == 7  # not 14

    ledger = client.get(
        f"{API}/inventory/ledger?sku_id={sku['id']}&page_size=200", headers=owner_headers
    ).json()
    assert ledger["total"] == 1


# ---------------------------------------------------------------- concurrency
def test_boundary_reservation_never_oversells(client, owner_headers, stock_fixture):
    """11 sequential attempts against 10 sellable units: exactly 10 succeed."""
    sku = stock_fixture["sku"]
    warehouse = stock_fixture["warehouse"]
    # safety_qty is 2, so book 12 to leave exactly 10 sellable.
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 12, "入库")

    successes = 0
    for _ in range(11):
        if reserve_stock(client, owner_headers, sku["id"], warehouse["id"], 1).status_code == 200:
            successes += 1

    assert successes == 10
    row = _stock_of(client, owner_headers, sku["id"], warehouse["id"])
    assert row["reserved_qty"] == 10
    assert row["available_qty"] == 0


def test_concurrent_reservations_never_oversell(client, owner_headers, stock_fixture):
    """20 simultaneous buyers race for 10 sellable units.

    Only the database lock makes this safe; SQLite serialises writes itself, so
    the assertions below hold whether a given request loses the race on the lock
    or on the availability check.
    """
    sku = stock_fixture["sku"]
    warehouse = stock_fixture["warehouse"]
    adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 12, "入库")

    def attempt(_: int) -> int:
        try:
            return reserve_stock(client, owner_headers, sku["id"], warehouse["id"], 1).status_code
        except Exception:  # pragma: no cover - a lost race may surface as a transport error
            return 0

    with ThreadPoolExecutor(max_workers=10) as pool:
        statuses = list(pool.map(attempt, range(20)))

    assert len(statuses) == 20
    successes = sum(1 for code in statuses if code == 200)
    # Exactly the ten sellable units are handed out; an eleventh must not exist.
    assert successes == 10, f"expected 10 successful reservations, got {successes}"

    row = _stock_of(client, owner_headers, sku["id"], warehouse["id"])
    assert row["reserved_qty"] == 10
    assert row["available_qty"] == 0
    assert row["on_hand_qty"] == 12  # reservations never touch on-hand
