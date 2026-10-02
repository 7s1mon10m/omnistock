"""Data access for users, roles and refresh tokens."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.role import Role
from app.models.user import RefreshToken, User, UserStatus
from app.utils.pagination import PageResult, paginate


def get_by_username(session: Session, username: str) -> User | None:
    stmt = select(User).where(User.username == username, User.deleted_at.is_(None))
    return session.scalar(stmt)


def get_by_email(session: Session, email: str) -> User | None:
    stmt = select(User).where(User.email == email, User.deleted_at.is_(None))
    return session.scalar(stmt)


def get(session: Session, user_id: int) -> User | None:
    user = session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return None
    return user


def list_users(
    session: Session,
    *,
    keyword: str | None = None,
    status: UserStatus | None = None,
    role: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    stmt = select(User).where(User.deleted_at.is_(None))
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            or_(User.username.like(pattern), User.full_name.like(pattern), User.email.like(pattern))
        )
    if status:
        stmt = stmt.where(User.status == status)
    if role:
        stmt = stmt.where(User.roles.any(Role.name == role))
    stmt = stmt.order_by(User.id.desc())
    return paginate(session, stmt, page, page_size)


def get_role_by_name(session: Session, name: str) -> Role | None:
    return session.scalar(select(Role).where(Role.name == name))


def list_roles(session: Session) -> list[Role]:
    return list(session.scalars(select(Role).order_by(Role.id)).all())


def ensure_role(session: Session, name: str, description: str = "", is_system: bool = True) -> Role:
    role = get_role_by_name(session, name)
    if role is None:
        role = Role(name=name, description=description, is_system=is_system)
        session.add(role)
        session.flush()
    return role


def create(
    session: Session,
    *,
    username: str,
    hashed_password: str,
    email: str = "",
    full_name: str = "",
    phone: str = "",
    roles: list[Role] | None = None,
) -> User:
    user = User(
        username=username,
        hashed_password=hashed_password,
        email=email,
        full_name=full_name,
        phone=phone,
    )
    if roles:
        user.roles = roles
    session.add(user)
    session.flush()
    return user


def save_refresh_token(
    session: Session,
    *,
    jti: str,
    user_id: int,
    expires_at,
    user_agent: str = "",
) -> RefreshToken:
    token = RefreshToken(jti=jti, user_id=user_id, expires_at=expires_at, user_agent=user_agent)
    session.add(token)
    session.flush()
    return token


def get_refresh_token(session: Session, jti: str) -> RefreshToken | None:
    return session.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
