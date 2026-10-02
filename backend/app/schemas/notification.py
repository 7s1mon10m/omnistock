"""通知的出入参。"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.models.notification import (
    DeliveryStatus,
    NotificationChannel,
    NotificationLevel,
)


class DeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: NotificationChannel
    status: DeliveryStatus
    endpoint: str
    attempts: int
    response_code: int | None = None
    last_error: str
    next_retry_at: dt.datetime | None = None
    sent_at: dt.datetime | None = None
    created_at: dt.datetime | None = None


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str
    level: NotificationLevel
    category: str
    ref_type: str
    ref_id: int | None = None
    recipient_id: int | None = None
    is_read: bool
    read_at: dt.datetime | None = None
    created_at: dt.datetime | None = None
    deliveries: list[DeliveryRead] = Field(default_factory=list)


class NotificationCreate(BaseModel):
    """手工建一条通知（也用于测试通道）。"""

    title: str = Field(min_length=1, max_length=160)
    body: str = Field(default="", max_length=4000)
    level: NotificationLevel = NotificationLevel.INFO
    category: str = Field(default="system", max_length=32)
    ref_type: str = Field(default="", max_length=32)
    ref_id: int | None = None
    recipient_id: int | None = None
    dispatch: bool = True


class NotificationSettingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    channel: NotificationChannel
    enabled: bool
    config: dict
    updated_at: dt.datetime | None = None


class NotificationSettingUpdate(BaseModel):
    enabled: bool | None = None
    config: dict | None = None


class UnreadCount(BaseModel):
    unread: int = 0
