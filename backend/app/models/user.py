"""User account, status and refresh-token bookkeeping."""

from __future__ import annotations

import datetime as dt
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import SoftDeleteMixin, TimestampMixin, enum_type
from app.models.role import Role, user_roles


class UserStatus(str, Enum):
    ACTIVE = "active"
    LOCKED = "locked"
    DISABLED = "disabled"


class User(Base, TimestampMixin, SoftDeleteMixin):
    """A team member.  Deletion is always logical so history stays intact."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    full_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        enum_type(UserStatus, "user_status"), default=UserStatus.ACTIVE, nullable=False
    )

    # Brute-force protection (see AUTH_MAX_LOGIN_ATTEMPTS / AUTH_LOCK_MINUTES).
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=None, nullable=True)

    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")

    @property
    def role_names(self) -> list[str]:
        return [role.name for role in self.roles]

    @property
    def is_locked(self) -> bool:
        if self.status == UserStatus.LOCKED:
            return True
        if self.locked_until and self.locked_until > dt.datetime.now(dt.timezone.utc).replace(tzinfo=None):
            return True
        return False

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<User {self.username}>"


class RefreshToken(Base, TimestampMixin):
    """Issued refresh tokens, so logout and rotation can revoke them."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (UniqueConstraint("jti", name="uq_refresh_tokens_jti"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user_agent: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    def is_valid(self, now: dt.datetime | None = None) -> bool:
        now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        return not self.revoked and self.expires_at > now
