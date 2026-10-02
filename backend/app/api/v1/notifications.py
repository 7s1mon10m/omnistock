"""Notification centre and channel settings."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.v1.guards import AdminGuard, ViewerGuard
from app.core.deps import DbSession
from app.models.notification import NotificationChannel
from app.repositories import notification_repo
from app.schemas.common import Page
from app.schemas.notification import (
    NotificationCreate,
    NotificationRead,
    NotificationSettingRead,
    NotificationSettingUpdate,
    UnreadCount,
)
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])

# 字面量路径必须声明在 /{notification_id}/... 之前，否则会被参数路由吞掉。
@router.get(
    "/settings/all", response_model=list[NotificationSettingRead], summary="全部通道配置"
)
def list_settings(session: DbSession, _: ViewerGuard) -> list[NotificationSettingRead]:
    rows = {row.channel: row for row in notification_repo.list_settings(session)}
    return [
        notification_service.to_setting_read(
            rows.get(channel), channel=channel
        )
        for channel in NotificationChannel
    ]


@router.put(
    "/settings/{channel}",
    response_model=NotificationSettingRead,
    summary="更新通道配置",
)
def update_setting(
    channel: NotificationChannel,
    payload: NotificationSettingUpdate,
    session: DbSession,
    user: AdminGuard,
) -> NotificationSettingRead:
    setting = notification_service.update_setting(
        session, channel, payload, operator_id=user.id
    )
    return notification_service.to_setting_read(setting)


@router.get("", response_model=Page[NotificationRead], summary="通知列表")
def list_notifications(
    session: DbSession,
    user: ViewerGuard,
    category: str | None = None,
    is_read: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[NotificationRead]:
    result = notification_repo.list_notifications(
        session,
        recipient_id=user.id,
        category=category,
        is_read=is_read,
        page=page,
        page_size=page_size,
    )
    return Page(
        items=[notification_service.to_read(row) for row in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/unread-count", response_model=UnreadCount, summary="未读数")
def unread_count(session: DbSession, user: ViewerGuard) -> UnreadCount:
    return UnreadCount(unread=notification_repo.count_unread(session, user.id))


@router.post("", response_model=NotificationRead, status_code=201, summary="发一条通知")
def create_notification(
    payload: NotificationCreate, session: DbSession, user: ViewerGuard
) -> NotificationRead:
    """Also used to smoke-test a channel: pass dispatch=true and check deliveries."""
    from app.models.notification import NotificationLevel

    notification = notification_service.notify(
        session,
        title=payload.title,
        body=payload.body,
        level=payload.level or NotificationLevel.INFO,
        category=payload.category,
        ref_type=payload.ref_type,
        ref_id=payload.ref_id,
        recipient_id=payload.recipient_id,
    )
    return notification_service.to_read(notification)


@router.post("/{notification_id}/read", response_model=NotificationRead, summary="标记已读")
def mark_read(
    notification_id: int, session: DbSession, user: ViewerGuard
) -> NotificationRead:
    notification = notification_service.get_or_404(session, notification_id)
    # 只有收件人本人（或广播）才能已读，避免 A 替 B 点掉。
    if notification.recipient_id is not None and notification.recipient_id != user.id:
        from app.core.errors import BusinessError, NOTIFICATION_NOT_FOUND

        raise BusinessError(NOTIFICATION_NOT_FOUND, http_status=404)
    notification = notification_service.mark_read(session, notification)
    return notification_service.to_read(notification)


@router.post("/read-all", response_model=UnreadCount, summary="全部已读")
def mark_all_read(session: DbSession, user: ViewerGuard) -> UnreadCount:
    from app.core.errors import BusinessError, NOTIFICATION_NOT_FOUND
    from app.models.base import utcnow

    listed = notification_repo.list_notifications(
        session, recipient_id=user.id, is_read=False, page=1, page_size=200
    )
    for notification in listed.items:
        if notification.recipient_id is None or notification.recipient_id == user.id:
            notification.is_read = True
            notification.read_at = utcnow()
    session.commit()
    return UnreadCount(unread=notification_repo.count_unread(session, user.id))
