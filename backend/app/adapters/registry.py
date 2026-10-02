"""Adapter registry.

Adding a platform is meant to be a one-file change: implement ``parse`` and
register it here (or decorate it with :func:`register` in M8, when real
Taobao/Douyin adapters arrive).
"""

from __future__ import annotations

from app.adapters.base import OrderAdapter
from app.adapters.csv_adapter import CsvOrderAdapter
from app.adapters.json_adapter import JsonOrderAdapter
from app.core.errors import ImportParseError

_ADAPTERS: list[OrderAdapter] = [CsvOrderAdapter(), JsonOrderAdapter()]


def register(adapter: OrderAdapter) -> OrderAdapter:
    _ADAPTERS.append(adapter)
    return adapter


def get_adapter(name: str) -> OrderAdapter:
    for adapter in _ADAPTERS:
        if adapter.name == name:
            return adapter
    raise ImportParseError(f"未知的导入格式：{name}")


def adapter_for_filename(filename: str) -> OrderAdapter:
    lowered = filename.lower()
    for adapter in _ADAPTERS:
        if lowered.endswith(adapter.extensions):
            return adapter
    raise ImportParseError(
        f"无法根据文件名判断格式：{filename or '(未提供文件名)'}，请上传 .csv 或 .json"
    )
