"""Adapter registry.

Adding a platform is meant to be a one-file change: implement ``parse`` and
register it here.  Nothing downstream — reservation, dedup, exceptions — needs
to know which platform an order came from.

Two kinds live here:

* **file** adapters (M2) turn an uploaded CSV/JSON into orders;
* **api** adapters (M8) do the same for a platform's API response.

``adapter_for_filename`` only considers adapters that actually declare file
extensions, so a platform adapter can never be picked up by accident just
because someone uploaded a file.
"""

from __future__ import annotations

from app.adapters.base import OrderAdapter
from app.adapters.csv_adapter import CsvOrderAdapter
from app.adapters.douyin_adapter import DouyinAdapter
from app.adapters.json_adapter import JsonOrderAdapter
from app.adapters.taobao_adapter import TaobaoAdapter
from app.core.errors import ImportParseError

_ADAPTERS: list[OrderAdapter] = [
    CsvOrderAdapter(),
    JsonOrderAdapter(),
    TaobaoAdapter(),
    DouyinAdapter(),
]

#: 平台适配器按 key 取，供渠道适配器配置与手动同步使用。
API_ADAPTERS: dict[str, OrderAdapter] = {
    "taobao": TaobaoAdapter(),
    "douyin": DouyinAdapter(),
}


def register(adapter: OrderAdapter) -> OrderAdapter:
    _ADAPTERS.append(adapter)
    return adapter


def get_adapter(name: str) -> OrderAdapter:
    for adapter in _ADAPTERS:
        if adapter.name == name:
            return adapter
    raise ImportParseError(f"未知的导入格式：{name}")


def get_api_adapter(key: str) -> OrderAdapter:
    adapter = API_ADAPTERS.get(key)
    if adapter is None:
        raise ImportParseError(f"未注册的渠道适配器：{key}")
    return adapter


def adapter_for_filename(filename: str) -> OrderAdapter:
    lowered = filename.lower()
    for adapter in _ADAPTERS:
        if adapter.extensions and lowered.endswith(adapter.extensions):
            return adapter
    raise ImportParseError(
        f"无法根据文件名判断格式：{filename or '(未提供文件名)'}，请上传 .csv 或 .json"
    )


def describe() -> list[dict]:
    """Every registered adapter, for the configuration screen."""
    rows: list[dict] = []
    seen: set[str] = set()
    for adapter in _ADAPTERS:
        if adapter.name in seen:
            continue
        seen.add(adapter.name)
        rows.append(
            {
                "key": adapter.name,
                "name": adapter.name,
                "kind": "api" if adapter.name in API_ADAPTERS else "file",
                "extensions": list(adapter.extensions),
            }
        )
    return rows
