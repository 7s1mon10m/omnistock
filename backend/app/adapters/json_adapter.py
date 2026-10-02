"""JSON order export adapter.

Accepts either a bare array of orders or ``{"orders": [...]}``, which covers both
a hand-written fixture and what an adapter wrapper tends to produce.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.adapters.base import ParsedImport, row_error
from app.core.errors import IMPORT_PARSE_ERROR, ImportParseError
from app.models.order import OrderSource
from app.schemas.order import OrderIn


class JsonOrderAdapter:
    name = "json"
    extensions = (".json",)
    source = OrderSource.IMPORT_JSON

    def parse(self, content: bytes, filename: str = "") -> ParsedImport:
        try:
            payload = json.loads(content.decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise ImportParseError("JSON 文件不是 UTF-8 编码") from exc
        except json.JSONDecodeError as exc:
            raise ImportParseError(
                f"JSON 解析失败：{exc.msg}（第 {exc.lineno} 行）",
                rows=[{"row": exc.lineno, "code": IMPORT_PARSE_ERROR, "message": exc.msg}],
            ) from exc

        if isinstance(payload, dict):
            payload = payload.get("orders", payload.get("items", []))
        if not isinstance(payload, list):
            raise ImportParseError("JSON 顶层必须是订单数组或 {\"orders\": [...]}")

        result = ParsedImport()
        for index, raw in enumerate(payload, start=1):
            try:
                result.orders.append(OrderIn.model_validate(raw))
            except ValidationError as exc:
                first = exc.errors()[0]
                field = ".".join(str(part) for part in first["loc"])
                result.row_errors.append(
                    row_error(index, IMPORT_PARSE_ERROR, f"{field}: {first['msg']}")
                )
        return result
