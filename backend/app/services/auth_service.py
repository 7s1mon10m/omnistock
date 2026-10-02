"""Login, token issuance/refresh and logout."""

from __future__ import annotations

import datetime as dt

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    AUTH_ACCOUNT_LOCKED,
    AUTH_INVALID_CREDENTIALS,
    AUTH_TOKEN_EXPIRED,
    AUTH_TOKEN_INVALID,
    BusinessError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    new_refresh_jti,
    refresh_token_expires_at,
    verify_password,
)
from app.models.user import RefreshToken, User, UserStatus
from app.repositories import user_repo
from app.schemas.auth import TokenPair
from app.schemas.user import UserRead
from app.services import permission_service


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _unlock_if_expired(user: User) -> None:
    """Clear the lock once AUTH_LOCK_MINUTES has elapsed."""
    if user.locked_until and user.locked_until <= _now():
        user.locked_until = None
        user.failed_login_attempts = 0
        if user.status == UserStatus.LOCKED:
            user.status = UserStatus.ACTIVE


def authenticate(session: Session, username: str, password: str) -> User:
    """Validate credentials, applying brute-force lockout."""
    user = user_repo.get_by_username(session, username)
    if user is None:
        # Same error for unknown users so the endpoint does not leak existence.
        raise BusinessError(AUTH_INVALID_CREDENTIALS, http_status=401)

    _unlock_if_expired(user)
    if user.is_locked:
        raise BusinessError(AUTH_ACCOUNT_LOCKED, http_status=401)

    if not verify_password(password, user.hashed_password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.AUTH_MAX_LOGIN_ATTEMPTS:
            user.locked_until = _now() + dt.timedelta(minutes=settings.AUTH_LOCK_MINUTES)
            user.status = UserStatus.LOCKED
            session.commit()
            raise BusinessError(
                AUTH_ACCOUNT_LOCKED,
                f"连续登录失败 {user.failed_login_attempts} 次，账号已锁定 "
                f"{settings.AUTH_LOCK_MINUTES} 分钟",
                http_status=401,
            )
        # Commit, not flush: the counter must survive into the next request.
        session.commit()
        raise BusinessError(AUTH_INVALID_CREDENTIALS, http_status=401)

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = _now()
    session.commit()
    return user


def issue_tokens(session: Session, user: User, user_agent: str = "") -> TokenPair:
    jti = new_refresh_jti()
    expires_at = dt.datetime.fromtimestamp(refresh_token_expires_at())
    user_repo.save_refresh_token(
        session, jti=jti, user_id=user.id, expires_at=expires_at, user_agent=user_agent
    )
    session.commit()
    return TokenPair(
        access_token=create_access_token(user.id, {"roles": user.role_names}),
        refresh_token=create_refresh_token(user.id, jti),
        expires_in=settings.AUTH_ACCESS_TTL_MINUTES * 60,
    )


def login(
    session: Session, username: str, password: str, user_agent: str = ""
) -> tuple[TokenPair, UserRead]:
    user = authenticate(session, username, password)
    tokens = issue_tokens(session, user, user_agent)
    return tokens, UserRead.from_user(user)


def refresh(session: Session, refresh_token: str) -> TokenPair:
    try:
        payload = decode_token(refresh_token)
    except jwt.ExpiredSignatureError:
        raise BusinessError(AUTH_TOKEN_EXPIRED, http_status=401) from None
    except jwt.PyJWTError:
        raise BusinessError(AUTH_TOKEN_INVALID, http_status=401) from None

    if payload.get("type") != "refresh":
        raise BusinessError(AUTH_TOKEN_INVALID, http_status=401)

    stored = user_repo.get_refresh_token(session, payload["jti"])
    if stored is None or not stored.is_valid():
        raise BusinessError(AUTH_TOKEN_EXPIRED, "刷新令牌已失效", http_status=401)

    user = user_repo.get(session, int(payload["sub"]))
    if user is None:
        raise BusinessError(AUTH_TOKEN_INVALID, http_status=401)

    # Rotate: the old refresh token cannot be reused.
    stored.revoked = True
    session.flush()
    return issue_tokens(session, user, stored.user_agent)


def logout(session: Session, refresh_token: str) -> None:
    try:
        payload = decode_token(refresh_token)
    except jwt.PyJWTError:
        return
    stored = user_repo.get_refresh_token(session, payload.get("jti", ""))
    if stored is not None:
        stored.revoked = True
        session.commit()


def revoke_all(session: Session, user_id: int) -> int:
    tokens = session.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False)
        )
    ).all()
    count = 0
    for token in tokens:
        token.revoked = True
        count += 1
    session.flush()
    return count


def bootstrap_admin(session: Session) -> User:
    """Create the initial administrator from configuration on first start."""
    existing = user_repo.get_by_username(session, settings.DEFAULT_ADMIN_USERNAME)
    if existing is not None:
        return existing
    permission_service.ensure_default_roles(session)
    admin_role = permission_service.roles_for(session, ["admin"])
    user = user_repo.create(
        session,
        username=settings.DEFAULT_ADMIN_USERNAME,
        hashed_password=hash_password(settings.DEFAULT_ADMIN_PASSWORD),
        email=settings.DEFAULT_ADMIN_EMAIL,
        full_name="系统管理员",
        roles=admin_role,
    )
    session.commit()
    return user
