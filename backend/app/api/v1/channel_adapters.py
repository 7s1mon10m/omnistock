"""Channel adapter configuration and manual sync.

A channel adapter is *code* (see :mod:`app.adapters`); this table only decides
which adapter a channel uses and with what parameters.  Connecting a new
platform is therefore "add one class + one row", with no change to any existing
logic.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.adapters import registry
from app.api.v1.guards import AdminGuard, OperatorGuard, ViewerGuard
from app.core.deps import DbSession
from app.core.errors import (
    ADAPTER_NOT_CONFIGURED,
    ADAPTER_NOT_FOUND,
    CHANNEL_NOT_FOUND,
    BusinessError,
)
from app.models.base import utcnow
from app.models.channel_adapter import AdapterSyncStatus, ChannelAdapter
from app.models.order import OrderSource
from app.repositories import channel_repo, order_repo
from app.schemas.report import (
    AdapterDescriptor,
    AdapterSyncResult,
    ChannelAdapterIn,
    ChannelAdapterRead,
    ChannelAdapterUpdate,
)
from app.services import order_import_service

router = APIRouter(prefix="/channel-adapters", tags=["channel-adapters"])


def _to_read(row: ChannelAdapter) -> ChannelAdapterRead:
    return ChannelAdapterRead(
        id=row.id,
        channel_id=row.channel_id,
        channel_code=row.channel.code if row.channel else "",
        channel_name=row.channel.name if row.channel else "",
        adapter_key=row.adapter_key,
        enabled=row.enabled,
        config=dict(row.config),
        sync_interval_minutes=row.sync_interval_minutes,
        last_sync_at=row.last_sync_at,
        last_sync_status=row.last_sync_status.value,
        last_sync_message=row.last_sync_message,
        remark=row.remark,
        created_at=row.created_at,
    )


@router.get("/descriptors", response_model=list[AdapterDescriptor], summary="可用适配器清单")
def list_descriptors(_: ViewerGuard) -> list[AdapterDescriptor]:
    rows = registry.describe()
    return [AdapterDescriptor(description=row["name"], **row) for row in rows]


@router.get("", response_model=list[ChannelAdapterRead], summary="渠道适配器配置列表")
def list_adapters(
    session: DbSession, _: ViewerGuard, channel_id: int | None = None
) -> list[ChannelAdapterRead]:
    stmt = select(ChannelAdapter)
    if channel_id is not None:
        stmt = stmt.where(ChannelAdapter.channel_id == channel_id)
    return [_to_read(row) for row in session.scalars(stmt)]


@router.post(
    "", response_model=ChannelAdapterRead, status_code=201, summary="配置渠道适配器"
)
def create_adapter(
    payload: ChannelAdapterIn, session: DbSession, _: AdminGuard
) -> ChannelAdapterRead:
    if channel_repo.get_channel(session, payload.channel_id) is None:
        raise BusinessError(CHANNEL_NOT_FOUND, http_status=404)
    if payload.adapter_key not in registry.API_ADAPTERS:
        raise BusinessError(
            ADAPTER_NOT_FOUND, f"没有 {payload.adapter_key} 这个适配器", http_status=404
        )

    existing = session.scalar(
        select(ChannelAdapter).where(ChannelAdapter.channel_id == payload.channel_id)
    )
    if existing is not None:
        raise BusinessError(ADAPTER_NOT_FOUND, "该渠道已配置适配器，请改用更新接口", http_status=409)

    row = ChannelAdapter(
        channel_id=payload.channel_id,
        adapter_key=payload.adapter_key,
        enabled=payload.enabled,
        config=payload.config,
        sync_interval_minutes=payload.sync_interval_minutes,
        remark=payload.remark,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_read(row)


@router.put("/{adapter_id}", response_model=ChannelAdapterRead, summary="更新适配器配置")
def update_adapter(
    adapter_id: int, payload: ChannelAdapterUpdate, session: DbSession, _: AdminGuard
) -> ChannelAdapterRead:
    row = session.get(ChannelAdapter, adapter_id)
    if row is None:
        raise BusinessError(ADAPTER_NOT_FOUND, http_status=404)
    if payload.adapter_key is not None:
        if payload.adapter_key not in registry.API_ADAPTERS:
            raise BusinessError(
                ADAPTER_NOT_FOUND, f"没有 {payload.adapter_key} 这个适配器", http_status=404
            )
        row.adapter_key = payload.adapter_key
    for field in ("enabled", "config", "sync_interval_minutes", "remark"):
        value = getattr(payload, field)
        if value is not None:
            setattr(row, field, value)
    session.commit()
    return _to_read(row)


@router.post("/{adapter_id}/sync", response_model=AdapterSyncResult, summary="手动触发一次同步")
def sync_now(
    adapter_id: int,
    session: DbSession,
    user: OperatorGuard,
    payload: dict | None = None,
) -> AdapterSyncResult:
    """Pull orders through the adapter and run them down the normal import path.

    The payload is the raw platform response.  Accepting it in the request body
    (rather than fetching it ourselves) keeps the adapter free of HTTP and makes
    a manual sync reproducible in tests.
    """
    import json

    row = session.get(ChannelAdapter, adapter_id)
    if row is None:
        raise BusinessError(ADAPTER_NOT_FOUND, http_status=404)
    if not row.enabled:
        raise BusinessError(
            ADAPTER_NOT_CONFIGURED, "该渠道的适配器尚未启用", http_status=424
        )

    adapter = registry.get_api_adapter(row.adapter_key)
    content = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")

    try:
        parsed = adapter.parse(content)
    except Exception as exc:  # noqa: BLE001 - one bad payload must not 500 the endpoint
        row.last_sync_at = utcnow()
        row.last_sync_status = AdapterSyncStatus.FAILED
        row.last_sync_message = f"解析失败：{type(exc).__name__}: {exc}"[:255]
        session.commit()
        raise BusinessError(
            ADAPTER_NOT_CONFIGURED, f"解析失败：{exc}", http_status=422
        ) from exc

    # 渠道身份来自配置，不是平台响应：平台不知道我们内部怎么称呼这个渠道，
    # 让适配器去猜 shop 名称会把渠道映射做错。
    channel_code = row.channel.code if row.channel else ""
    for order in parsed.orders:
        if not order.channel_code and channel_code:
            order.channel_code = channel_code

    result = order_import_service.import_orders(
        session,
        parsed,
        source=OrderSource.ADAPTER,
        filename=f"{row.adapter_key}-sync.json",
        operator_id=user.id,
    )

    # 「全是重复」是同步正常的结果 —— 平台把同一批订单又推了一遍。只有真的
    # 有行解析/导入失败才算失败，否则看板会满是红色的正常同步。
    if result.failed_rows and not result.created_orders:
        status = AdapterSyncStatus.FAILED
    elif result.failed_rows:
        status = AdapterSyncStatus.PARTIAL
    else:
        status = AdapterSyncStatus.OK
    row.last_sync_at = utcnow()
    row.last_sync_status = status
    row.last_sync_message = (
        f"新建 {result.created_orders} · 重复 {result.duplicate_orders} · 失败 {result.failed_rows}"
    )
    session.commit()

    logs = order_repo.list_sync_logs(session, channel_id=row.channel_id, page=1, page_size=1)
    return AdapterSyncResult(
        adapter_key=row.adapter_key,
        channel_id=row.channel_id,
        result="created" if result.created_orders else "duplicate",
        message=row.last_sync_message,
        created_orders=result.created_orders,
        duplicate_orders=result.duplicate_orders,
        failed_rows=result.failed_rows,
        sync_log_id=logs.items[0].id if logs.items else None,
    )
