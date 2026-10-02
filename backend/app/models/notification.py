"""站内通知、投递记录与通道配置（M6）。

设计要点：**通知本体**和**投递**分开。

一条通知「低库存告警」可能要同时发到站内、邮件和 Webhook，三个通道的成败
互不影响。把投递单独建表，才能做到「站内已读、Webhook 还在重试」这种真实
状态，也才能把每次尝试的时间与响应码留下来。
"""

from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, enum_type


class NotificationChannel(str, Enum):
    INAPP = "inapp"      # 站内消息
    EMAIL = "email"      # 邮件（SMTP）
    WEBHOOK = "webhook"  # HTTP 回调


class NotificationLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DeliveryStatus(str, Enum):
    PENDING = "pending"    # 待发送
    SENT = "sent"          # 已成功
    RETRYING = "retrying"  # 失败后已安排重试
    FAILED = "failed"      # 重试耗尽，彻底失败
    SKIPPED = "skipped"    # 通道未启用 / 未配置，跳过


class Notification(Base, TimestampMixin):
    """一条站内通知。``recipient_id`` 为空表示广播给所有人。"""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_read", "recipient_id", "is_read"),
        Index("ix_notifications_category", "category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    level: Mapped[NotificationLevel] = mapped_column(
        enum_type(NotificationLevel, "notification_level"),
        default=NotificationLevel.INFO,
        nullable=False,
    )
    # 分类用于前端分组，例如 alert / purchase / transfer / system。
    category: Mapped[str] = mapped_column(String(32), default="system", nullable=False)

    # 关联的业务对象，点开通知能直接跳过去。
    ref_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    ref_id: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True)

    recipient_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), default=None, nullable=True
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)

    # 幂等键：同一件事（如同一张采购单）只提醒一次。
    dedup_key: Mapped[str | None] = mapped_column(
        String(96), default=None, nullable=True, unique=True
    )

    deliveries: Mapped[list["NotificationDelivery"]] = relationship(
        back_populates="notification",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Notification {self.id} {self.category} read={self.is_read}>"


class NotificationDelivery(Base, TimestampMixin):
    """一条通知在某个通道上的一次投递尝试（含重试）。"""

    __tablename__ = "notification_deliveries"
    __table_args__ = (Index("ix_deliveries_pending", "status", "next_retry_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False
    )

    channel: Mapped[NotificationChannel] = mapped_column(
        enum_type(NotificationChannel, "notification_channel"), nullable=False
    )
    status: Mapped[DeliveryStatus] = mapped_column(
        enum_type(DeliveryStatus, "delivery_status"), default=DeliveryStatus.PENDING, nullable=False
    )
    # 投递目标：邮箱地址 / Webhook URL / 用户名。
    endpoint: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    response_code: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True)
    last_error: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    next_retry_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)

    notification: Mapped[Notification] = relationship(back_populates="deliveries")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Delivery {self.channel} status={self.status} attempts={self.attempts}>"


class NotificationSetting(Base, TimestampMixin):
    """每个通道的全局配置。``config`` 里放 URL / 收件人列表 / 开关等。"""

    __tablename__ = "notification_settings"
    __table_args__ = (UniqueConstraint("channel", name="uq_notification_setting_channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[NotificationChannel] = mapped_column(
        enum_type(NotificationChannel, "notification_channel"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<NotificationSetting {self.channel} enabled={self.enabled}>"
