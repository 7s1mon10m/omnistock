"""Shared FastAPI dependencies: database session, current user, role guard."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    AUTH_ACCOUNT_LOCKED,
    AUTH_TOKEN_EXPIRED,
    AUTH_TOKEN_INVALID,
    PERMISSION_DENIED,
    BusinessError,
)
from app.core.security import decode_token
from app.db import get_session
from app.models.user import User, UserStatus
from app.services.permission_service import user_has_any_role

DbSession = Annotated[Session, Depends(get_session)]


def _extract_token(authorization: str | None) -> str:
    if not authorization:
        raise BusinessError(AUTH_TOKEN_INVALID, http_status=401)
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise BusinessError(AUTH_TOKEN_INVALID, http_status=401)
    return token.strip()


def get_current_user(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the caller from the ``Authorization: Bearer <jwt>`` header."""
    import jwt

    token = _extract_token(authorization)
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:  # pragma: no cover - timing dependent
        raise BusinessError(AUTH_TOKEN_EXPIRED, http_status=401) from None
    except jwt.PyJWTError:
        raise BusinessError(AUTH_TOKEN_INVALID, http_status=401) from None

    if payload.get("type") != "access":
        raise BusinessError(AUTH_TOKEN_INVALID, http_status=401)

    user = session.get(User, int(payload["sub"]))
    if user is None:
        raise BusinessError(AUTH_TOKEN_INVALID, http_status=401)
    if user.status == UserStatus.LOCKED:
        raise BusinessError(AUTH_ACCOUNT_LOCKED, http_status=401)
    if user.status != UserStatus.ACTIVE:
        raise BusinessError(PERMISSION_DENIED, "账号未启用", http_status=403)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: str):
    """Build a dependency that only lets the listed roles through."""

    def _guard(user: CurrentUser) -> User:
        if not user_has_any_role(user, set(roles)):
            raise BusinessError(
                PERMISSION_DENIED,
                f"该操作需要以下角色之一：{', '.join(roles)}",
                http_status=403,
            )
        return user

    return Depends(_guard)


def require_admin() -> User:
    """Convenience guard used by the admin-only routers."""
    return require_roles("admin")


def api_prefix() -> str:
    return settings.API_V1_PREFIX
