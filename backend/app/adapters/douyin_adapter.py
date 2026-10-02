"""抖音电商开放平台订单适配器。

抖音把商品行放在 ``items``、金额放在 ``pay_amount``（**分**），与淘宝的字段名
和单位都不一样 —— 这正是需要适配器这一层的原因：下游的占用、去重、异常逻辑
完全不需要知道订单来自哪个平台。
"""

from __future__ import annotations

import json

from app.adapters.base import ParsedImport, row_error
from app.core.errors import IMPORT_PARSE_ERROR, ImportParseError
from app.schemas.order import OrderIn, OrderItemIn


class DouyinAdapter:
    name = "douyin"
    extensions: tuple[str, ...] = ()

    def parse(self, content: bytes, filename: str = "") -> ParsedImport:  # noqa: ARG002
        try:
            payload = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImportParseError(f"抖音响应不是合法 JSON：{exc}") from exc

        raw_orders = payload.get("orders") or payload.get("data") or []
        if not isinstance(raw_orders, list):
            raise ImportParseError("抖音响应里没有订单数组")

        result = ParsedImport()
        for index, raw in enumerate(raw_orders, start=1):
            try:
                result.orders.append(self._one(raw))
            except (KeyError, TypeError, ValueError) as exc:
                result.row_errors.append(
                    row_error(index, IMPORT_PARSE_ERROR, f"字段解析失败：{exc}",
                              str(raw.get("order_id", ""))[:64])
                )

        if not result.orders and not result.row_errors:
            raise ImportParseError("抖音响应里没有可导入的订单")
        return result

    def _one(self, raw: dict) -> OrderIn:
        items = []
        for line in raw.get("items") or raw.get("sku_list") or []:
            items.append(
                OrderItemIn(
                    channel_product_code=str(
                        line.get("outer_sku_id") or line.get("sku_id") or ""
                    ),
                    quantity=int(line.get("item_num") or line.get("quantity") or 0),
                    # 抖音的 pay_amount 已经是「分」，不要再乘 100
                    unit_price_cents=int(line.get("pay_amount") or line.get("price") or 0),
                )
            )
        if not items:
            raise ValueError("订单没有商品行")
        return OrderIn(
            channel_code=str(raw.get("shop_code") or raw.get("shop_name") or ""),
            shop_code=str(raw.get("shop_id") or "") or None,
            channel_order_no=str(raw.get("order_id") or raw.get("parent_order_id") or ""),
            buyer_nick=str(raw.get("buyer_name") or raw.get("open_id") or ""),
            paid_at=str(raw.get("pay_time") or raw.get("create_time") or "") or None,
            items=items,
        )
