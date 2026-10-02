"""Channel adapters.

An adapter turns a platform's export into :class:`~app.schemas.order.OrderIn`
objects.  Real platform APIs are plugged in at M8; M2 ships CSV and JSON, which
already covers how most small teams pull orders out of a backend.
"""

from app.adapters.base import OrderAdapter, ParsedImport, row_error
from app.adapters.csv_adapter import CsvOrderAdapter
from app.adapters.json_adapter import JsonOrderAdapter
from app.adapters.registry import adapter_for_filename, get_adapter

__all__ = [
    "CsvOrderAdapter",
    "JsonOrderAdapter",
    "OrderAdapter",
    "ParsedImport",
    "adapter_for_filename",
    "get_adapter",
    "row_error",
]
