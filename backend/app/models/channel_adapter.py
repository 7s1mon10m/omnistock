"""渠道适配器配置（M8）。

适配器本身是代码（``app/adapters`` 里的类），这张表只存**某个渠道启用哪个适配器、
以及它的凭证/参数**。把配置和代码分开，接一个新平台就是「加一个类 + 建一条配置」，
不需要改任何已有逻辑。
"""

from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, enum_type
from app.models.channel import Channel


class AdapterSyncStatus(str, Enum):
    NEVER = "never"      # 从未同步
    OK = "ok"            # 上次同步成功
    PARTIAL = "partial"  # 部分成功（有错误行）
    FAILED = "failed"


class ChannelAdapter(Base, TimestampMixin):
    __tablename__ = "channel_adapters"
    __table_args__ = (UniqueConstraint("channel_id", name="uq_channel_adapters_channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    # 对应 app.adapters.registry 里注册的 key，例如 taobao / douyin / csv / json
    adapter_key: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 凭证与参数；敏感值应通过环境变量注入而不是落库。
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    last_sync_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    last_sync_status: Mapped[AdapterSyncStatus] = mapped_column(
        enum_type(AdapterSyncStatus, "adapter_sync_status"),
        default=AdapterSyncStatus.NEVER,
        nullable=False,
    )
    last_sync_message: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    remark: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    channel: Mapped[Channel] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<ChannelAdapter ch={self.channel_id} key={self.adapter_key!r} on={self.enabled}>"
