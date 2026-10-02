"""CSV / JSON order import: parsing, grouping, mapping resolution and reporting."""

from __future__ import annotations

import pytest

from app.core.config import settings
from conftest import (
    API,
    create_channel,
    create_mapping,
    create_shop,
    import_orders,
    order_payload,
    stock_of,
    uniq,
)


def _upload(client, headers, filename: str, content: str):
    return client.post(
        f"{API}/orders/import",
        files={"file": (filename, content.encode("utf-8"), "text/csv")},
        headers=headers,
    )


def _csv(rows: list[str]) -> str:
    header = (
        "channel_code,shop_code,channel_order_no,channel_product_code,"
        "quantity,unit_price,buyer_nick,warehouse_code,paid_at\n"
    )
    return header + "\n".join(rows) + "\n"


# ------------------------------------------------------------------------ CSV
def test_csv_rows_sharing_an_order_number_become_one_order(client, operator_headers, catalog):
    channel = create_channel(client, operator_headers, code=uniq("CSV"))
    mapping_code = uniq("P")
    create_mapping(client, operator_headers, channel["id"], mapping_code, catalog["sku"]["id"])

    csv_text = _csv(
        [
            f"{channel['code']},,CSV-ORDER-1,{mapping_code},2,99.00,张*三,,2026-10-01 10:00:00",
            f"{channel['code']},,CSV-ORDER-1,{mapping_code},3,99.00,张*三,,2026-10-01 10:00:00",
        ]
    )
    response = _upload(client, operator_headers, "orders.csv", csv_text)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_orders"] == 1
    assert body["reserved_orders"] == 1
    assert body["failed_rows"] == 0

    orders = client.get(f"{API}/orders?keyword=CSV-ORDER-1", headers=operator_headers).json()
    assert orders["total"] == 1
    detail = client.get(f"{API}/orders/{orders['items'][0]['id']}", headers=operator_headers).json()
    # Two CSV lines, one order, and the quantities were folded together.
    assert len(detail["items"]) == 2
    assert detail["total_quantity"] == 5
    assert detail["total_amount_cents"] == 5 * 9900


def test_csv_accepts_a_bom_and_chinese_utf8(client, operator_headers, catalog):
    """Excel 另存为 CSV 会带 BOM，必须能直接吃下去。"""
    channel = create_channel(client, operator_headers, code=uniq("BOM"))
    mapping_code = uniq("P")
    create_mapping(client, operator_headers, channel["id"], mapping_code, catalog["sku"]["id"])

    csv_text = "\ufeff" + _csv(
        [f"{channel['code']},,BOM-1,{mapping_code},1,10,李*四,,2026-10-01 12:00:00"]
    )
    response = _upload(client, operator_headers, "orders.csv", csv_text)
    assert response.status_code == 200, response.text
    assert response.json()["created_orders"] == 1


def test_a_bad_row_is_reported_with_its_line_number(client, operator_headers, catalog):
    channel = create_channel(client, operator_headers, code=uniq("BAD"))
    mapping_code = uniq("P")
    create_mapping(client, operator_headers, channel["id"], mapping_code, catalog["sku"]["id"])

    csv_text = _csv(
        [
            f"{channel['code']},,BAD-1,{mapping_code},2,10,ok,,2026-10-01 10:00:00",
            f"{channel['code']},,BAD-2,{mapping_code},abc,10,坏行,,2026-10-01 10:00:00",
            f"{channel['code']},,BAD-3,{mapping_code},1,10,好行,,2026-10-01 10:00:00",
        ]
    )
    body = _upload(client, operator_headers, "orders.csv", csv_text).json()
    # One bad line did not cost us the other two.
    assert body["created_orders"] == 2
    assert body["failed_rows"] == 1
    assert body["errors"][0]["row"] == 3
    assert "quantity" in body["errors"][0]["message"]


def test_unmapped_channel_product_code_fails_only_that_order(client, operator_headers, catalog):
    channel = create_channel(client, operator_headers, code=uniq("MAP"))
    good = uniq("P")
    create_mapping(client, operator_headers, channel["id"], good, catalog["sku"]["id"])

    body = import_orders(
        client,
        operator_headers,
        [
            order_payload(channel["code"], "MAP-OK", [{"channel_product_code": good, "quantity": 1}]),
            order_payload(
                channel["code"], "MAP-BAD", [{"channel_product_code": "NOT-MAPPED", "quantity": 1}]
            ),
        ],
    ).json()

    assert body["created_orders"] == 1
    assert body["failed_rows"] == 1
    assert body["errors"][0]["code"] == 40020
    assert "NOT-MAPPED" in body["errors"][0]["message"]


def test_unknown_channel_and_shop_are_reported_per_order(client, operator_headers, catalog):
    channel = create_channel(client, operator_headers, code=uniq("UNK"))
    mapping_code = uniq("P")
    create_mapping(client, operator_headers, channel["id"], mapping_code, catalog["sku"]["id"])

    body = import_orders(
        client,
        operator_headers,
        [
            order_payload("NO-SUCH-CHANNEL", "U-1", [{"channel_product_code": mapping_code, "quantity": 1}]),
            order_payload(channel["code"], "U-2", [{"channel_product_code": mapping_code, "quantity": 1}], shop_code="NO-SHOP"),
        ],
    ).json()

    codes = sorted(error["code"] for error in body["errors"])
    assert body["failed_rows"] == 2
    assert codes == [40420, 40421]


def test_unknown_warehouse_code_is_rejected(client, operator_headers, catalog):
    channel = create_channel(client, operator_headers, code=uniq("WH"))
    mapping_code = uniq("P")
    create_mapping(client, operator_headers, channel["id"], mapping_code, catalog["sku"]["id"])

    body = import_orders(
        client,
        operator_headers,
        [
            order_payload(
                channel["code"],
                "W-1",
                [{"channel_product_code": mapping_code, "quantity": 1}],
                warehouse_code="NO-WH",
            )
        ],
    ).json()
    assert body["errors"][0]["code"] == 40412


def test_csv_missing_a_required_column_is_a_parse_error(client, operator_headers):
    response = _upload(client, operator_headers, "orders.csv", "channel_code,quantity\nTB,1\n")
    assert response.status_code == 422
    assert response.json()["code"] == 42210
    assert any("channel_order_no" in row["message"] for row in response.json()["detail"])


def test_an_empty_upload_is_refused(client, operator_headers):
    response = _upload(client, operator_headers, "orders.csv", "")
    assert response.status_code == 400
    assert response.json()["code"] == 40022


def test_a_header_only_csv_creates_nothing(client, operator_headers):
    response = _upload(client, operator_headers, "orders.csv", _csv([]))
    assert response.status_code == 400
    assert response.json()["code"] == 40022


def test_row_limit_is_enforced(client, operator_headers, catalog, monkeypatch):
    channel = create_channel(client, operator_headers, code=uniq("LIM"))
    mapping_code = uniq("P")
    create_mapping(client, operator_headers, channel["id"], mapping_code, catalog["sku"]["id"])
    monkeypatch.setattr(settings, "IMPORT_MAX_ROWS", 1)

    body = import_orders(
        client,
        operator_headers,
        [
            order_payload(channel["code"], "L-1", [{"channel_product_code": mapping_code, "quantity": 1}]),
            order_payload(channel["code"], "L-2", [{"channel_product_code": mapping_code, "quantity": 1}]),
        ],
    )
    assert body.status_code == 400
    assert body.json()["code"] == 40021


def test_unsupported_file_extension_is_refused(client, operator_headers):
    response = _upload(client, operator_headers, "orders.xlsx", "a,b\n1,2\n")
    assert response.status_code == 422


# ----------------------------------------------------------------------- JSON
def test_json_import_records_a_batch_and_its_sync_log(client, operator_headers, catalog):
    channel = create_channel(client, operator_headers, code=uniq("JS"))
    shop = create_shop(client, operator_headers, channel["id"])
    mapping_code = uniq("P")
    create_mapping(client, operator_headers, channel["id"], mapping_code, catalog["sku"]["id"])

    body = import_orders(
        client,
        operator_headers,
        [
            order_payload(
                channel["code"],
                "JS-1",
                [{"channel_product_code": mapping_code, "quantity": 4, "unit_price_cents": 500}],
                shop_code=shop["code"],
                warehouse_code=catalog["warehouse"]["code"],
            )
        ],
    ).json()
    assert body["created_orders"] == 1

    batches = client.get(f"{API}/orders/import-batches", headers=operator_headers).json()
    assert batches["items"][0]["created_orders"] == 1
    assert batches["items"][0]["source"] == "import_json"

    logs = client.get(f"{API}/orders/sync-logs?channel_order_no=JS-1", headers=operator_headers).json()
    assert logs["total"] == 1
    assert logs["items"][0]["result"] == "created"

    stock = stock_of(
        client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"]
    )
    assert stock["reserved_qty"] == 4


def test_json_items_must_have_a_positive_quantity(client, operator_headers, catalog):
    channel = create_channel(client, operator_headers, code=uniq("JQ"))
    response = import_orders(
        client,
        operator_headers,
        [order_payload(channel["code"], "JQ-1", [{"channel_product_code": "X", "quantity": 0}])],
    )
    # Rejected by the request schema before any channel lookup happens.
    assert response.status_code == 422


def test_csv_template_is_downloadable(client, operator_headers):
    response = client.get(f"{API}/orders/import-template.csv", headers=operator_headers)
    assert response.status_code == 200
    assert "channel_order_no" in response.text
    assert "attachment" in response.headers["content-disposition"]


def test_warehouse_role_cannot_import_orders(client, warehouse_headers, catalog):
    response = import_orders(
        client,
        warehouse_headers,
        [order_payload("ANY", "X-1", [{"channel_product_code": "X", "quantity": 1}])],
    )
    assert response.status_code == 403
    assert response.json()["code"] == 40301


@pytest.mark.parametrize("quantity", [1, 7])
def test_reserved_quantity_matches_the_order(client, operator_headers, catalog, quantity):
    channel = create_channel(client, operator_headers, code=uniq("Q"))
    mapping_code = uniq("P")
    create_mapping(client, operator_headers, channel["id"], mapping_code, catalog["sku"]["id"])

    import_orders(
        client,
        operator_headers,
        [
            order_payload(
                channel["code"],
                f"Q-{quantity}",
                [{"channel_product_code": mapping_code, "quantity": quantity}],
            )
        ],
    )
    stock = stock_of(client, operator_headers, catalog["sku"]["id"], catalog["warehouse"]["id"])
    assert stock["reserved_qty"] == quantity
    assert stock["on_hand_qty"] == 100
