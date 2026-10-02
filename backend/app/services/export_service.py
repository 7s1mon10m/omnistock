"""CSV 导出。

两个细节决定了导出的文件能不能真的用：

* **UTF-8 BOM。** Excel 在中文 Windows 上默认用 GBK 打开 CSV，没有 BOM 就是
  一屏乱码。加 BOM 是唯一可靠的做法（``utf-8-sig``）。
* **行数上限。** 不加限制的一次导出会把内存打满，还会把请求挂住。超过上限
  直接报错（40070），把范围缩小再来，而不是悄悄截断 —— 截断会让报表说谎。
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from typing import Any

from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.errors import EXPORT_ROW_LIMIT_EXCEEDED, BusinessError


def _bom() -> str:
    return "\ufeff"


def build_csv(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """Render rows with a BOM so Excel opens them without mojibake."""
    if len(rows) > settings.EXPORT_MAX_ROWS:
        raise BusinessError(
            EXPORT_ROW_LIMIT_EXCEEDED,
            f"共 {len(rows)} 行，超过上限 {settings.EXPORT_MAX_ROWS}，请缩小日期范围",
            detail={"rows": len(rows), "limit": settings.EXPORT_MAX_ROWS},
            http_status=400,
        )

    buffer = io.StringIO()
    buffer.write(_bom())
    writer = csv.writer(buffer, delimiter=settings.EXPORT_CSV_DELIMITER)
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue()


def _content_disposition(filename: str) -> str:
    """HTTP headers are latin-1 only, so a Chinese filename must be encoded.

    Sends both forms: ``filename`` (an ASCII fallback for old clients) and
    ``filename*`` (RFC 5987, what modern browsers actually use).  Without
    ``filename*`` Excel would save the file as a string of percent escapes.
    """
    from urllib.parse import quote

    ascii_name = "".join(ch if ch.isascii() and ch.isalnum() or ch in "-_" else "_" for ch in filename)
    return f'attachment; filename="{ascii_name}.csv"; filename*=UTF-8\'\'{quote(filename)}.csv'


def csv_response(filename: str, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> StreamingResponse:
    content = build_csv(headers, rows)
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


def from_dicts(headers: Sequence[str], keys: Sequence[str], rows: Sequence[dict]) -> str:
    """Convenience wrapper that pulls ``keys`` out of each dict in order."""
    matrix = [[row.get(key, "") for key in keys] for row in rows]
    return build_csv(headers, matrix)
