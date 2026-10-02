"""User schemas."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import User, UserStatus


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    full_name: str
    phone: str
    status: UserStatus
    roles: list[str] = Field(default_factory=list)
    last_login_at: dt.datetime | None = None
    created_at: dt.datetime | None = None

    @classmethod
    def from_user(cls, user: User) -> "UserRead":
        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            phone=user.phone,
            status=user.status,
            roles=user.role_names,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
        )


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: str = Field(default="", max_length=128)
    full_name: str = Field(default="", max_length=64)
    phone: str = Field(default="", max_length=32)
    roles: list[str] = Field(default_factory=lambda: ["operator"])


class UserUpdate(BaseModel):
    email: str | None = Field(default=None, max_length=128)
    full_name: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=32)
    status: UserStatus | None = None
    roles: list[str] | None = None


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    is_system: bool
    permissions: list[str] = Field(default_factory=list)
