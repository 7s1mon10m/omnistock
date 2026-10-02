"""Notification data access."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.notification import (
    DeliveryStatus,
    Notification,
    NotificationChannel,
    NotificationDelivery,
    NotificationSetting,
)
from app.utils.pagination import PageResult, paginate


def get(session: Session, notification_id: int) -> Notification | None:
    return session.get(Notification, notification_id)


def get_by_dedup(session: Session, dedup_key: str) -> Notification | None:
    stmt = select(Notification).where(Notification.dedup_key == dedup_key)
    return session.scalar(stmt)


def list_notifications(
    session: Session,
    *,
    recipient_id: int | None,
    category: str | None = None,
    is_read: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    """接收人可见 = 发给本人的 + 广播（recipient_id 为空）。

    ``recipient_id`` 为 None 表示调用方不按人过滤（例如后台任务）。
    """
    stmt = select(Notification)
    if recipient_id is not None:
        stmt = stmt.where(
            or_(
                Notification.recipient_id == recipient_id,
                Notification.recipient_id.is_(None),
            )
        )
    if category:
        stmt = stmt.where(Notification.category == category)
    if is_read is not None:
        stmt = stmt.where(Notification.is_read.is_(is_read))
    stmt = stmt.order_by(Notification.id.desc())
    return paginate(session, stmt, page, page_size)


def count_unread(session: Session, recipient_id: int | None) -> int:
    stmt = select(func.count()).select_from(Notification).where(Notification.is_read.is_(False))
    if recipient_id is not None:
        stmt = stmt.where(
            or_(
                Notification.recipient_id == recipient_id,
                Notification.recipient_id.is_(None),
            )
        )
    return session.scalar(stmt) or 0


def create(session: Session, **fields) -> Notification:
    notification = Notification(**fields)
    session.add(notification)
    session.flush()
    return notification


# ---------------------------------------------------------------- deliveries
def create_delivery(session: Session, **fields) -> NotificationDelivery:
    delivery = NotificationDelivery(**fields)
    session.add(delivery)
    session.flush()
    return delivery


def list_deliveries(
    session: Session, notification_id: int
) -> list[NotificationDelivery]:
    stmt = (
        select(NotificationDelivery)
        .where(NotificationDelivery.notification_id == notification_id)
        .order_by(NotificationDelivery.id)
    )
    return list(session.scalars(stmt))


def due_deliveries(
    session: Session, *, now: dt.datetime | None = None, limit: int = 50
) -> list[NotificationDelivery]:
    """到点该重试的投递：retrying 且 next_retry_at 已到。"""
    now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    stmt = (
        select(NotificationDelivery)
        .where(
            NotificationDelivery.status.in_([DeliveryStatus.RETRYING, DeliveryStatus.PENDING]),
            NotificationDelivery.next_retry_at.is_not(None),
            NotificationDelivery.next_retry_at <= now,
        )
        .order_by(NotificationDelivery.next_retry_at)
        .limit(limit)
    )
    return list(session.scalars(stmt))


# ----------------------------------------------------------------- settings
def get_setting(session: Session, channel: NotificationChannel) -> NotificationSetting | None:
    stmt = select(NotificationSetting).where(NotificationSetting.channel == channel)
    return session.scalar(stmt)


def list_settings(session: Session) -> list[NotificationSetting]:
    stmt = select(NotificationSetting).order_by(NotificationSetting.id)
    return list(session.scalars(stmt))


def upsert_setting(session: Session, channel: NotificationChannel, **fields) -> NotificationSetting:
    setting = get_setting(session, channel)
    if setting is None:
        setting = NotificationSetting(channel=channel, **fields)
        session.add(setting)
    else:
        for key, value in fields.items():
            setattr(setting, key, value)
    session.flush()
    return setting
