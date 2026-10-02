"""审计日志。

只有写入接口，没有更新与删除 —— 审计表一旦可改，它就不再是审计。

``actor_name`` 是冗余存下来的：用户后来被停用或改名，历史记录仍然要能读懂
「当时是谁干的」。同理，请求体只留一个截断的预览，不存完整 payload，避免把
密码之类的字段写进一张谁都能查的表。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audit import AuditLog
from app.utils.pagination import PageResult, paginate

#: 请求体预览的最大长度。
PREVIEW_MAX = 500

#: The version prefix that must be stripped before reading the resource name.
VERSION_PREFIX = "/api/v1/"

#: 这些字段即使出现在请求体里也不记录。
SENSITIVE_KEYS = {"password", "new_password", "old_password", "token", "secret"}


def record(
    session: Session,
    *,
    actor_id: int | None,
    actor_name: str,
    action: str,
    resource_type: str,
    resource_id: str = "",
    method: str = "",
    path: str = "",
    status_code: int = 0,
    ip: str = "",
    user_agent: str = "",
    request_id: str = "",
    summary: str = "",
    detail: dict[str, Any] | None = None,
    payload_preview: str = "",
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor_id,
        actor_name=actor_name,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id)[:48],
        method=method,
        path=path[:255],
        status_code=status_code,
        ip=ip[:64],
        user_agent=user_agent[:255],
        request_id=request_id[:64],
        summary=summary[:255],
        detail=detail or {},
        payload_preview=payload_preview[:PREVIEW_MAX],
    )
    session.add(entry)
    session.flush()
    return entry


def list_logs(
    session: Session,
    *,
    actor_id: int | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    start_at: dt.datetime | None = None,
    end_at: dt.datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(AuditLog)
    if actor_id is not None:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"%{action}%"))
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if resource_id:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    if start_at:
        stmt = stmt.where(AuditLog.created_at >= start_at)
    if end_at:
        stmt = stmt.where(AuditLog.created_at <= end_at)
    stmt = stmt.order_by(AuditLog.id.desc())
    return paginate(session, stmt, page, page_size)


def purge_expired(session: Session) -> int:
    """Delete entries older than the retention window.  Returns how many went."""
    cutoff = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(
        days=settings.AUDIT_LOG_RETENTION_DAYS
    )
    rows = list(session.scalars(select(AuditLog).where(AuditLog.created_at < cutoff)))
    for entry in rows:
        session.delete(entry)
    session.commit()
    return len(rows)


def sanitize_preview(payload: Any) -> str:
    """A short, secret-free rendering of a request body."""
    if payload is None:
        return ""
    text = str(payload)
    lowered = text.lower()
    for key in SENSITIVE_KEYS:
        if key in lowered:
            return "<已省略：包含敏感字段>"
    return text[:PREVIEW_MAX]


def _segments(path: str) -> list[str]:
    """Path segments below ``/api/v1/`` — the version prefix is not a resource."""
    rest = path[len(VERSION_PREFIX) :] if path.startswith(VERSION_PREFIX) else path.lstrip("/")
    return [p for p in rest.split("/") if p]


def action_for(method: str, path: str) -> str:
    """Turn ``POST /api/v1/inventory/adjust`` into ``inventory.adjust``.

    The version prefix must be stripped first, otherwise every action comes out
    as ``v1.something`` and the audit log is unsearchable by resource.
    """
    parts = _segments(path)
    if not parts:
        return method.lower()
    resource = parts[0]
    verb = parts[-1] if len(parts) > 1 and parts[-1] != resource else method.lower()
    return f"{resource}.{verb}"[:64]


def resource_type_for(path: str) -> str:
    return (_segments(path)[0] if _segments(path) else "")[:48]
