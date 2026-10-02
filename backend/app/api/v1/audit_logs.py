"""Audit log queries.  **Read only** — there is no update or delete endpoint.

If an audit trail can be edited, it stops being an audit trail.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query

from app.api.v1.guards import AdminGuard
from app.core.deps import DbSession
from app.repositories import user_repo
from app.schemas.common import Page
from app.schemas.report import AuditLogRead
from app.services import audit_service, inventory_service

router = APIRouter(prefix="/audit-logs", tags=["audit"])


def _to_read(row) -> AuditLogRead:
    return AuditLogRead(
        id=row.id,
        actor_id=row.actor_id,
        actor_name=row.actor_name,
        action=row.action,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        method=row.method,
        path=row.path,
        status_code=row.status_code,
        ip=row.ip,
        user_agent=row.user_agent,
        request_id=row.request_id,
        summary=row.summary,
        detail=dict(row.detail),
        created_at=row.created_at,
    )


@router.get("", response_model=Page[AuditLogRead], summary="审计日志（只读）")
def list_audit_logs(
    session: DbSession,
    _: AdminGuard,
    actor: str | None = None,
    action: str | None = None,
    resource: str | None = None,
    resource_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[AuditLogRead]:
    """支持按操作人（用户名或姓名）、动作、资源对象与时间范围检索。"""
    actor_id = None
    if actor:
        user = user_repo.get_by_username(session, actor)
        if user is None:
            # 也允许按姓名查，找不到就返回空而不是报错
            actor_id = -1
        else:
            actor_id = user.id

    result = audit_service.list_logs(
        session,
        actor_id=actor_id,
        action=action,
        resource_type=resource,
        resource_id=resource_id,
        start_at=inventory_service.parse_dt(start),
        end_at=inventory_service.parse_dt(end),
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[_to_read(row) for row in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
