"""Notifications: creation, dispatch and retry.

The interesting part is :func:`retry_due`, which implements exponential backoff.
2 → 4 → 8 → 16 seconds, giving up after ``NOTIFY_MAX_RETRIES`` attempts.

A retry that keeps the notification invisible is the failure mode this module
exists to prevent: the in-app row is created **first** and marked read-or-not
independently of delivery, so a broken webhook can never hide a low-stock
warning from the person who needs to see it.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    NOTIFICATION_CHANNEL_INVALID,
    NOTIFICATION_NOT_FOUND,
    BusinessError,
)
from app.models.base import utcnow
from app.models.notification import (
    DeliveryStatus,
    Notification,
    NotificationChannel,
    NotificationDelivery,
    NotificationLevel,
)
from app.repositories import notification_repo
from app.schemas.notification import (
    DeliveryRead,
    NotificationRead,
    NotificationSettingRead,
    NotificationSettingUpdate,
)
from app.services.channels import email as email_channel
from app.services.channels import inapp as inapp_channel
from app.services.channels import webhook as webhook_channel

_DISPATCHERS = {
    NotificationChannel.INAPP: inapp_channel.deliver,
    NotificationChannel.EMAIL: email_channel.deliver,
    NotificationChannel.WEBHOOK: webhook_channel.deliver,
}


# ------------------------------------------------------------------- create
def notify(
    session: Session,
    *,
    title: str,
    body: str = "",
    level: NotificationLevel = NotificationLevel.INFO,
    category: str = "system",
    ref_type: str = "",
    ref_id: int | None = None,
    recipient_id: int | None = None,
    dedup_key: str | None = None,
    channels: list[NotificationChannel] | None = None,
    operator_id: int | None = None,
) -> Notification:
    """Create a notification and immediately try to deliver it.

    ``dedup_key`` makes this idempotent: the same event (a purchase order
    approval, say) notifies once no matter how many times it is replayed.
    """
    if dedup_key:
        existing = notification_repo.get_by_dedup(session, dedup_key)
        if existing is not None:
            return existing

    notification = notification_repo.create(
        session,
        title=title,
        body=body,
        level=level,
        category=category,
        ref_type=ref_type,
        ref_id=ref_id,
        recipient_id=recipient_id,
        dedup_key=dedup_key,
    )
    try:
        session.flush()
    except IntegrityError:
        # 另一个并发请求刚用同一个 dedup_key 建好了。
        session.rollback()
        existing = notification_repo.get_by_dedup(session, dedup_key or "")
        if existing is not None:
            return existing
        raise

    if channels is None:
        channels = default_channels(session)
    dispatch(session, notification, channels=channels, operator_id=operator_id)
    session.commit()
    return notification


def default_channels(session: Session) -> list[NotificationChannel]:
    """System default: whatever the settings table has enabled, else ``NOTIFY_CHANNELS``."""
    enabled = [
        row.channel
        for row in notification_repo.list_settings(session)
        if row.enabled and row.channel != NotificationChannel.INAPP
    ]
    if enabled:
        # 站内永远开着 —— 它不依赖任何外部配置。
        return [NotificationChannel.INAPP, *enabled]

    parsed: list[NotificationChannel] = []
    for raw in settings.NOTIFY_CHANNELS.split(","):
        token = raw.strip()
        if not token:
            continue
        try:
            parsed.append(NotificationChannel(token))
        except ValueError:
            # 配置里写了个不认识的通道名，忽略它而不是让整个通知流程挂掉。
            continue
    return parsed or [NotificationChannel.INAPP]


# ----------------------------------------------------------------- dispatch
def dispatch(
    session: Session,
    notification: Notification,
    *,
    channels: list[NotificationChannel] | None = None,
    operator_id: int | None = None,
) -> list[NotificationDelivery]:
    """Create one delivery per channel and attempt it immediately."""
    results: list[NotificationDelivery] = []
    for channel in channels or []:
        if channel not in _DISPATCHERS:
            raise BusinessError(
                NOTIFICATION_CHANNEL_INVALID, f"不支持的通道 {channel}", http_status=400
            )

        setting = notification_repo.get_setting(session, channel)
        config = dict(setting.config) if setting else {}
        enabled = setting.enabled if setting else (channel == NotificationChannel.INAPP)
        endpoint = str(config.get("endpoint") or config.get("recipients") or "")

        delivery = notification_repo.create_delivery(
            session,
            notification_id=notification.id,
            channel=channel,
            status=DeliveryStatus.PENDING,
            endpoint=endpoint[:255],
            attempts=0,
        )
        if not enabled:
            delivery.status = DeliveryStatus.SKIPPED
            delivery.last_error = "通道未启用"
            results.append(delivery)
            continue

        results.append(_attempt(session, notification, delivery))
    return results


def _attempt(
    session: Session, notification: Notification, delivery: NotificationDelivery
) -> NotificationDelivery:
    """Run one delivery attempt and record the outcome."""
    deliver = _DISPATCHERS[delivery.channel]
    try:
        status, code, error = deliver(
            session,
            notification_id=notification.id,
            endpoint=delivery.endpoint,
            title=notification.title,
            body=notification.body,
            level=notification.level.value,
        )
    except BusinessError as exc:
        # 通道未配置（邮件无 SMTP）——立即失败，不重试。
        status, code, error = DeliveryStatus.FAILED, None, exc.message[:200]
    except Exception as exc:  # noqa: BLE001 - a bad channel must not kill the batch
        status, code, error = DeliveryStatus.RETRYING, None, f"{type(exc).__name__}: {exc}"[:200]

    delivery.attempts += 1
    delivery.status = status
    delivery.response_code = code
    delivery.last_error = error[:255]

    if status == DeliveryStatus.SENT:
        delivery.sent_at = utcnow()
        delivery.next_retry_at = None
    elif status == DeliveryStatus.RETRYING and delivery.attempts < settings.NOTIFY_MAX_RETRIES:
        delivery.next_retry_at = utcnow() + dt.timedelta(
            seconds=_backoff_seconds(delivery.attempts)
        )
    else:
        # 重试预算用尽，或这个失败不值得重试。
        delivery.next_retry_at = None
        if status == DeliveryStatus.RETRYING:
            delivery.status = DeliveryStatus.FAILED
    return delivery


def _backoff_seconds(attempts: int) -> int:
    """2, 4, 8, 16 … seconds, capped so a stuck channel doesn't schedule in a year."""
    exponent = max(0, attempts - 1)
    return min(settings.NOTIFY_RETRY_BASE_SECONDS * (2**exponent), 3600)


# -------------------------------------------------------------------- retry
def retry_due(session: Session, *, limit: int = 50, now: dt.datetime | None = None) -> int:
    """Retry every delivery whose backoff has elapsed.  Returns how many ran."""
    now = now or utcnow()
    pending = notification_repo.due_deliveries(session, now=now, limit=limit)
    for delivery in pending:
        notification = delivery.notification
        if notification is None:
            continue
        _attempt(session, notification, delivery)
    session.commit()
    return len(pending)


# --------------------------------------------------------------------- read
def get_or_404(session: Session, notification_id: int) -> Notification:
    notification = notification_repo.get(session, notification_id)
    if notification is None:
        raise BusinessError(NOTIFICATION_NOT_FOUND, http_status=404)
    return notification


def mark_read(session: Session, notification: Notification) -> Notification:
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = utcnow()
        session.commit()
    return notification


def to_read(notification: Notification) -> NotificationRead:
    return NotificationRead(
        id=notification.id,
        title=notification.title,
        body=notification.body,
        level=notification.level,
        category=notification.category,
        ref_type=notification.ref_type,
        ref_id=notification.ref_id,
        recipient_id=notification.recipient_id,
        is_read=notification.is_read,
        read_at=notification.read_at,
        created_at=notification.created_at,
        deliveries=[to_delivery_read(row) for row in notification.deliveries],
    )


def to_delivery_read(delivery: NotificationDelivery) -> DeliveryRead:
    return DeliveryRead(
        id=delivery.id,
        channel=delivery.channel,
        status=delivery.status,
        endpoint=delivery.endpoint,
        attempts=delivery.attempts,
        response_code=delivery.response_code,
        last_error=delivery.last_error,
        next_retry_at=delivery.next_retry_at,
        sent_at=delivery.sent_at,
        created_at=delivery.created_at,
    )


# ----------------------------------------------------------------- settings
def to_setting_read(row, *, channel: NotificationChannel | None = None) -> NotificationSettingRead:
    resolved = row.channel if row is not None else channel
    # 站内通道没有配置行时也是开着的（见 dispatch），展示上要跟实际行为一致。
    default_enabled = resolved == NotificationChannel.INAPP
    return NotificationSettingRead(
        id=row.id if row is not None else None,
        channel=resolved,
        enabled=row.enabled if row is not None else default_enabled,
        config=dict(row.config) if row is not None else {},
        updated_at=row.updated_at if row is not None else None,
    )


def update_setting(
    session: Session,
    channel: NotificationChannel,
    payload: NotificationSettingUpdate,
    *,
    operator_id: int | None = None,
):
    changes: dict = {}
    if payload.enabled is not None:
        changes["enabled"] = payload.enabled
    if payload.config is not None:
        changes["config"] = payload.config
    if operator_id is not None:
        changes["updated_by"] = operator_id
    setting = notification_repo.upsert_setting(session, channel, **changes)
    # 必须提交：通道配置要活过这个请求，否则它对下一次通知毫无影响。
    session.commit()
    return setting
