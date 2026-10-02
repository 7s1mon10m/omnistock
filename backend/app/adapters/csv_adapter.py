"""CSV order export adapter.

Expected columns (header row required, order of columns does not matter):

    channel_code, shop_code, channel_order_no, channel_product_code,
    quantity, unit_price, buyer_nick, warehouse_code, paid_at

Only ``channel_code``, ``channel_order_no``, ``channel_product_code`` and
``quantity`` are mandatory.  Rows sharing the same
``(channel_code, shop_code, channel_order_no)`` are folded into one order with
several lines — which is exactly how Taobao/Douyin exports look.

One broken line never aborts the file: it is reported per row number and the
remaining rows are still imported.
"""

from __future__ import annotations

import csv
import datetime as dt
import io

from app.adapters.base import ParsedImport, row_error
from app.core.config import settings
from app.core.errors import IMPORT_PARSE_ERROR, ImportParseError
from app.models.order import OrderSource
from app.schemas.order import OrderIn, OrderItemIn

REQUIRED_COLUMNS = ("channel_code", "channel_order_no", "channel_product_code", "quantity")
OPTIONAL_COLUMNS = (
    "shop_code",
    "unit_price",
    "unit_price_cents",
    "buyer_nick",
    "warehouse_code",
    "paid_at",
)
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

#: Data starts on line 2 because line 1 is the header.
FIRST_DATA_ROW = 2

DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def _to_cents(row: dict[str, str]) -> int:
    """Accept either ``unit_price_cents`` or ``unit_price`` (yuan)."""
    raw_cents = (row.get("unit_price_cents") or "").strip()
    if raw_cents:
        try:
            return max(0, int(float(raw_cents)))
        except ValueError as exc:
            raise ValueError(f"unit_price_cents 不是数字：{raw_cents}") from exc

    raw_yuan = (row.get("unit_price") or "").strip()
    if not raw_yuan:
        return 0
    try:
        return max(0, round(float(raw_yuan) * 100))
    except ValueError as exc:
        raise ValueError(f"unit_price 不是数字：{raw_yuan}") from exc


def _to_quantity(raw: str) -> int:
    text = (raw or "").strip()
    if not text:
        raise ValueError("quantity 不能为空")
    try:
        value = int(float(text))
    except ValueError as exc:
        raise ValueError(f"quantity 不是数字：{text}") from exc
    if value <= 0:
        raise ValueError(f"quantity 必须大于 0：{text}")
    return value


def _to_dt(raw: str | None) -> dt.datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    normalized = text.replace("/", "-").replace("T", " ")
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    raise ValueError(f"paid_at 格式无法识别：{text}")


class CsvOrderAdapter:
    name = "csv"
    extensions = (".csv", ".txt")
    source = OrderSource.IMPORT_CSV

    def parse(self, content: bytes, filename: str = "") -> ParsedImport:
        reader = csv.DictReader(io.StringIO(self._decode(content)))
        header = [self._clean(name) for name in (reader.fieldnames or [])]
        if not header or not any(header):
            raise ImportParseError("CSV 缺少表头行")

        missing = [column for column in REQUIRED_COLUMNS if column not in header]
        if missing:
            raise ImportParseError(
                f"CSV 缺少必需列：{', '.join(missing)}",
                rows=[
                    {"row": 1, "code": IMPORT_PARSE_ERROR, "message": f"缺少列 {column}"}
                    for column in missing
                ],
            )

        result = ParsedImport()
        # Grouped by (channel, shop, order no) — a Taobao export puts one line
        # per order item, so several rows usually describe one order.
        meta: dict[tuple[str, str, str], dict] = {}
        lines: dict[tuple[str, str, str], list[OrderItemIn]] = {}

        for offset, raw_row in enumerate(reader):
            row_no = FIRST_DATA_ROW + offset
            row = {
                self._clean(key): (value or "").strip()
                for key, value in raw_row.items()
                if key is not None
            }
            if not any(row.values()):
                continue  # csv yields an empty dict for a trailing blank line

            key = (
                row.get("channel_code", ""),
                row.get("shop_code", ""),
                row.get("channel_order_no", ""),
            )
            try:
                if not key[0] or not key[2]:
                    raise ValueError("channel_code 与 channel_order_no 不能为空")
                product_code = row.get("channel_product_code", "")
                if not product_code:
                    raise ValueError("channel_product_code 不能为空")
                quantity = _to_quantity(row.get("quantity", ""))
                unit_price_cents = _to_cents(row)
                paid_at = _to_dt(row.get("paid_at"))
            except ValueError as exc:
                result.row_errors.append(row_error(row_no, IMPORT_PARSE_ERROR, str(exc), key[2]))
                continue

            entry = meta.setdefault(
                key,
                {"buyer_nick": "", "warehouse_code": None, "paid_at": None, "first_row": row_no},
            )
            entry["buyer_nick"] = entry["buyer_nick"] or row.get("buyer_nick", "")
            entry["warehouse_code"] = entry["warehouse_code"] or (row.get("warehouse_code") or None)
            # A later line may carry the timestamp an earlier one omitted.
            if paid_at and entry["paid_at"] is None:
                entry["paid_at"] = paid_at

            lines.setdefault(key, []).append(
                OrderItemIn(
                    channel_product_code=product_code,
                    quantity=quantity,
                    unit_price_cents=unit_price_cents,
                )
            )

        orders: list[OrderIn] = []
        for key, grouped_lines in lines.items():
            entry = meta[key]
            orders.append(
                OrderIn(
                    channel_code=key[0],
                    shop_code=key[1] or None,
                    channel_order_no=key[2],
                    buyer_nick=entry["buyer_nick"],
                    warehouse_code=entry["warehouse_code"],
                    paid_at=entry["paid_at"],
                    items=grouped_lines,
                )
            )
        result.orders = orders
        # An empty result is not a parse error — the service turns it into
        # IMPORT_EMPTY so the caller gets the more precise business code.
        return result

    @staticmethod
    def _clean(value: str | None) -> str:
        return (value or "").strip().lstrip("\ufeff").lower()

    @staticmethod
    def _decode(content: bytes) -> str:
        for encoding in (settings.IMPORT_ENCODING, "utf-8", "gb18030"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise ImportParseError(f"文件编码无法识别，请另存为 {settings.IMPORT_ENCODING} 或 UTF-8")


def empty_template() -> str:
    """The CSV header the UI offers as a download."""
    return ",".join(ALL_COLUMNS) + "\n"


__all__ = ["CsvOrderAdapter", "empty_template"]
