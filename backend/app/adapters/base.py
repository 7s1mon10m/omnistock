"""The adapter contract shared by every channel importer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.schemas.order import ImportErrorRow, OrderIn


@dataclass
class ParsedImport:
    """Result of parsing one uploaded file.

    Parse level problems (a bad quantity, an unreadable date) land in
    ``row_errors`` instead of aborting the whole file, so one broken line never
    costs the operator the other 499 rows.
    """

    orders: list[OrderIn] = field(default_factory=list)
    row_errors: list[ImportErrorRow] = field(default_factory=list)


class OrderAdapter(Protocol):
    """Turns raw file content into order payloads."""

    name: str
    extensions: tuple[str, ...]
    #: The :class:`~app.models.order.OrderSource` this adapter records on import.
    source: object

    def parse(self, content: bytes, filename: str = "") -> ParsedImport:  # pragma: no cover
        ...


def row_error(row: int, code: int, message: str, channel_order_no: str = "") -> ImportErrorRow:
    return ImportErrorRow(
        row=row, code=code, message=message, channel_order_no=channel_order_no
    )
