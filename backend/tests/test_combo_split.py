"""Bundle (组合商品) explosion and all-or-nothing reservation."""

from __future__ import annotations

from conftest import API, adjust_stock, create_sku, create_spu, create_warehouse, uniq


def _setup(client, headers):
    """Two component SKUs and a bundle SKU under a bundle-typed SPU.

    The component/bundle SKUs are shared across tests (they carry no state of
    their own); the warehouse is fresh per call so stock and reservations from
    one test never leak into the next.
    """
    tag = uniq("B")
    warehouse = create_warehouse(client, headers, name=f"组合测试仓{tag}", code=f"WH-{tag}")
    component_spu = create_spu(client, headers, "SPU-COMP", "组件商品")

    shampoo = create_sku(
        client, headers, component_spu["id"], sku_code="SHAMPOO-500", spec_json={"v": "500ml"}
    )
    conditioner = create_sku(
        client, headers, component_spu["id"], sku_code="CONDITIONER-500", spec_json={"v": "500ml"}
    )

    bundle_spu = create_spu(client, headers, "SPU-SET", "洗护套装", type_="bundle")
    bundle = create_sku(client, headers, bundle_spu["id"], sku_code="SET-01", spec_json={"v": "set"})

    return {
        "warehouse": warehouse,
        "shampoo": shampoo,
        "conditioner": conditioner,
        "bundle": bundle,
        "bundle_spu": bundle_spu,
        "component_spu": component_spu,
    }


def _set_components(client, headers, bundle_id: int, components: list[dict]):
    return client.put(
        f"{API}/bundles/{bundle_id}/components",
        json={"components": components},
        headers=headers,
    )


def test_components_can_only_be_set_on_a_bundle_spu(client, owner_headers):
    warehouse = create_warehouse(client, owner_headers, name="类型校验仓", code="WH-TYPE")
    single_spu = create_spu(client, owner_headers, "SPU-SINGLE-T", "普通商品")
    plain = create_sku(client, owner_headers, single_spu["id"])
    other = create_sku(client, owner_headers, single_spu["id"])

    response = _set_components(
        client, owner_headers, plain["id"], [{"component_sku_id": other["id"], "quantity": 1}]
    )
    assert response.status_code == 400
    assert response.json()["code"] == 40013
    assert warehouse  # created for isolation between tests


def test_setting_components_returns_the_bundle_structure(client, owner_headers):
    fixture = _setup(client, owner_headers)
    response = _set_components(
        client,
        owner_headers,
        fixture["bundle"]["id"],
        [
            {"component_sku_id": fixture["shampoo"]["id"], "quantity": 1},
            {"component_sku_id": fixture["conditioner"]["id"], "quantity": 2},
        ],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["bundle_sku_code"] == "SET-01"
    assert {c["component_sku_code"]: c["quantity"] for c in body["components"]} == {
        "SHAMPOO-500": 1,
        "CONDITIONER-500": 2,
    }


def test_a_bundle_cannot_reference_itself(client, owner_headers):
    fixture = _setup(client, owner_headers)
    response = _set_components(
        client, owner_headers, fixture["bundle"]["id"],
        [{"component_sku_id": fixture["bundle"]["id"], "quantity": 1}],
    )
    assert response.status_code == 409
    assert response.json()["code"] == 40907


def test_bundles_cannot_be_nested(client, owner_headers):
    fixture = _setup(client, owner_headers)
    _set_components(
        client, owner_headers, fixture["bundle"]["id"],
        [{"component_sku_id": fixture["shampoo"]["id"], "quantity": 1}],
    )

    # A second bundle that tries to use the first one as a component.
    extra_spu = create_spu(client, owner_headers, "SPU-SET-2", "另一个套装", type_="bundle")
    outer = create_sku(client, owner_headers, extra_spu["id"], sku_code="SET-02")

    response = _set_components(
        client, owner_headers, outer["id"],
        [{"component_sku_id": fixture["bundle"]["id"], "quantity": 1}],
    )
    assert response.status_code == 400
    assert response.json()["code"] == 40011


def test_missing_or_duplicated_components_are_refused(client, owner_headers):
    fixture = _setup(client, owner_headers)
    bundle_id = fixture["bundle"]["id"]

    missing = _set_components(
        client, owner_headers, bundle_id, [{"component_sku_id": 987654, "quantity": 1}]
    )
    assert missing.status_code == 409
    assert missing.json()["code"] == 40907

    duplicated = _set_components(
        client, owner_headers, bundle_id,
        [
            {"component_sku_id": fixture["shampoo"]["id"], "quantity": 1},
            {"component_sku_id": fixture["shampoo"]["id"], "quantity": 3},
        ],
    )
    assert duplicated.status_code == 409
    assert duplicated.json()["code"] == 40907


def test_reserving_a_bundle_reserves_each_component(client, owner_headers):
    fixture = _setup(client, owner_headers)
    warehouse = fixture["warehouse"]
    _set_components(
        client, owner_headers, fixture["bundle"]["id"],
        [
            {"component_sku_id": fixture["shampoo"]["id"], "quantity": 1},
            {"component_sku_id": fixture["conditioner"]["id"], "quantity": 1},
        ],
    )

    for sku in (fixture["shampoo"], fixture["conditioner"]):
        assert adjust_stock(client, owner_headers, sku["id"], warehouse["id"], 20, "备货").status_code == 200

    response = client.post(
        f"{API}/inventory/reserve-bundle",
        json={"bundle_sku_id": fixture["bundle"]["id"], "warehouse_id": warehouse["id"], "quantity": 3},
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    transactions = response.json()
    assert len(transactions) == 2
    assert {tx["sku_id"] for tx in transactions} == {
        fixture["shampoo"]["id"],
        fixture["conditioner"]["id"],
    }
    assert all(tx["qty_delta"] == 3 for tx in transactions)

    # Each component's reserved count went up by exactly the bundle quantity.
    rows = client.get(
        f"{API}/inventory?warehouse_id={warehouse['id']}&page_size=200", headers=owner_headers
    ).json()["items"]
    reserved = {row["sku_id"]: row["reserved_qty"] for row in rows}
    assert reserved[fixture["shampoo"]["id"]] == 3
    assert reserved[fixture["conditioner"]["id"]] == 3
    # On-hand is untouched by a reservation.
    assert {row["sku_id"]: row["on_hand_qty"] for row in rows}[fixture["shampoo"]["id"]] == 20


def test_a_short_component_blocks_the_whole_bundle(client, owner_headers):
    """All-or-nothing: no component may end up half-reserved."""
    fixture = _setup(client, owner_headers)
    warehouse = fixture["warehouse"]
    _set_components(
        client, owner_headers, fixture["bundle"]["id"],
        [
            {"component_sku_id": fixture["shampoo"]["id"], "quantity": 1},
            {"component_sku_id": fixture["conditioner"]["id"], "quantity": 1},
        ],
    )

    # Plenty of shampoo, almost no conditioner.
    adjust_stock(client, owner_headers, fixture["shampoo"]["id"], warehouse["id"], 50, "备货")
    adjust_stock(client, owner_headers, fixture["conditioner"]["id"], warehouse["id"], 2, "备货")

    response = client.post(
        f"{API}/inventory/reserve-bundle",
        json={"bundle_sku_id": fixture["bundle"]["id"], "warehouse_id": warehouse["id"], "quantity": 5},
        headers=owner_headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == 40906
    assert response.json()["detail"]["shortages"]

    # The abundant component must not carry a partial reservation.
    rows = client.get(
        f"{API}/inventory?warehouse_id={warehouse['id']}&page_size=200", headers=owner_headers
    ).json()["items"]
    assert all(row["reserved_qty"] == 0 for row in rows)


def test_buildable_quantity_is_the_weakest_component(client, owner_headers):
    fixture = _setup(client, owner_headers)
    warehouse = fixture["warehouse"]
    _set_components(
        client, owner_headers, fixture["bundle"]["id"],
        [
            {"component_sku_id": fixture["shampoo"]["id"], "quantity": 1},
            {"component_sku_id": fixture["conditioner"]["id"], "quantity": 2},
        ],
    )
    adjust_stock(client, owner_headers, fixture["shampoo"]["id"], warehouse["id"], 10, "备货")
    adjust_stock(client, owner_headers, fixture["conditioner"]["id"], warehouse["id"], 9, "备货")

    body = client.get(
        f"{API}/bundles/{fixture['bundle']['id']}?warehouse_id={warehouse['id']}",
        headers=owner_headers,
    ).json()

    # Shampoo supports 10 bundles, conditioner (2 each) only 4.
    assert body["buildable_qty"] == 4
    availability = {c["component_sku_code"]: c["available_qty"] for c in body["components"]}
    assert availability["SHAMPOO-500"] == 10
    assert availability["CONDITIONER-500"] == 9


def test_setting_components_replaces_the_previous_list(client, owner_headers):
    fixture = _setup(client, owner_headers)
    bundle_id = fixture["bundle"]["id"]

    _set_components(
        client, owner_headers, bundle_id,
        [{"component_sku_id": fixture["shampoo"]["id"], "quantity": 1}],
    )
    replaced = _set_components(
        client, owner_headers, bundle_id,
        [{"component_sku_id": fixture["conditioner"]["id"], "quantity": 4}],
    )
    assert replaced.status_code == 200
    components = replaced.json()["components"]
    assert len(components) == 1
    assert components[0]["component_sku_code"] == "CONDITIONER-500"
    assert components[0]["quantity"] == 4


def test_a_sku_with_components_reports_itself_as_a_bundle(client, owner_headers):
    fixture = _setup(client, owner_headers)
    _set_components(
        client, owner_headers, fixture["bundle"]["id"],
        [{"component_sku_id": fixture["shampoo"]["id"], "quantity": 1}],
    )

    listing = client.get(
        f"{API}/skus?spu_id={fixture['bundle_spu']['id']}", headers=owner_headers
    ).json()
    assert listing["items"][0]["is_bundle"] is True

    plain = client.get(
        f"{API}/skus?spu_id={fixture['component_spu']['id']}", headers=owner_headers
    ).json()
    assert all(item["is_bundle"] is False for item in plain["items"])
