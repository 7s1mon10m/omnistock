"""审计日志（M8）。**只写不读改** —— 没有任何更新或删除入口。"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin
from app.models.user import User


class AuditLog(Base, TimestampMixin):
    """一次写操作的留痕。

    ``actor_name`` 是冗余存下来的：用户后来被停用或改名，历史记录仍然要能读懂
    「当时是谁干的」。这也意味着审计表刻意不对 ``users`` 做强引用。
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_actor", "actor_id"),
        Index("ix_audit_action", "action"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
        Index("ix_audit_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, nullable=True
    )
    actor_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    # 规范化动作名，例如 product.create / inventory.adjust / shipment.ship
    action: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    resource_type: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    resource_id: Mapped[str] = mapped_column(String(48), default="", nullable=False)

    method: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    path: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    user_agent: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    summary: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # 结构化补充信息（请求体摘要等），不存敏感字段。
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    payload_preview: Mapped[str] = mapped_column(Text, default="", nullable=False)

    actor: Mapped[User | None] = relationship(lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<AuditLog {self.action} {self.resource_type}#{self.resource_id}>"
