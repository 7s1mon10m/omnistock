"""淘宝开放平台订单适配器。

字段名按平台返回的结构取值，缺失的按空处理而不是报错 —— 一个字段缺失不该
让整批同步失败，把能导入的都导入、坏的那几行单独报出来更有用。
"""

from __future__ import annotations

import json
from typing import Any

from app.adapters.base import ParsedImport, row_error
from app.core.errors import IMPORT_PARSE_ERROR, ImportParseError
from app.schemas.order import OrderIn, OrderItemIn


def _cents(value: Any) -> int:
    """淘宝的金额是「元」的字符串，统一转成分再入库。"""
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return 0


class TaobaoAdapter:
    name = "taobao"
    extensions: tuple[str, ...] = ()

    def parse(self, content: bytes, filename: str = "") -> ParsedImport:  # noqa: ARG002
        try:
            payload = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImportParseError(f"淘宝响应不是合法 JSON：{exc}") from exc

        raw_orders = payload.get("orders") or payload.get("trades") or []
        if not isinstance(raw_orders, list):
            raise ImportParseError("淘宝响应里没有订单数组")

        result = ParsedImport()
        for index, raw in enumerate(raw_orders, start=1):
            try:
                result.orders.append(self._one(raw))
            except (KeyError, TypeError, ValueError) as exc:
                result.row_errors.append(
                    row_error(index, IMPORT_PARSE_ERROR, f"字段解析失败：{exc}",
                              str(raw.get("tid", ""))[:64])
                )

        if not result.orders and not result.row_errors:
            raise ImportParseError("淘宝响应里没有可导入的订单")
        return result

    def _one(self, raw: dict) -> OrderIn:
        items = []
        for line in raw.get("orders") or raw.get("order_lines") or []:
            items.append(
                OrderItemIn(
                    channel_product_code=str(line.get("outer_sku_id") or line.get("num_iid") or ""),
                    quantity=int(line.get("num") or 0),
                    unit_price_cents=_cents(line.get("price") or line.get("payment") or 0),
                )
            )
        if not items:
            raise ValueError("订单没有商品行")
        return OrderIn(
            channel_code=str(raw.get("shop_code") or raw.get("seller_nick") or ""),
            shop_code=str(raw.get("shop_id") or "") or None,
            channel_order_no=str(raw.get("tid") or raw.get("order_id") or ""),
            buyer_nick=str(raw.get("buyer_nick") or ""),
            paid_at=str(raw.get("pay_time") or raw.get("created") or "") or None,
            items=items,
        )
