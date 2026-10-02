"""User and role management."""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from app.api.v1.guards import AdminGuard
from app.core.deps import DbSession
from app.core.errors import ROLE_NOT_FOUND, USERNAME_DUPLICATE, USER_NOT_FOUND, BusinessError
from app.core.security import hash_password
from app.models.user import User, UserStatus
from app.repositories import user_repo
from app.schemas.common import Page
from app.schemas.user import RoleRead, UserCreate, UserRead, UserUpdate
from app.services import permission_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/roles", response_model=list[RoleRead], summary="角色与权限清单")
def list_roles(session: DbSession, _: AdminGuard) -> list[RoleRead]:
    roles = user_repo.list_roles(session)
    return [
        RoleRead(
            id=role.id,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            permissions=sorted(p.code for p in role.permissions),
        )
        for role in roles
    ]


@router.get("", response_model=Page[UserRead], summary="用户列表")
def list_users(
    session: DbSession,
    _: AdminGuard,
    keyword: str | None = None,
    status: UserStatus | None = None,
    role: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Page[UserRead]:
    result = user_repo.list_users(
        session, keyword=keyword, status=status, role=role, page=page, page_size=page_size
    )
    return Page(
        items=[UserRead.from_user(u) for u in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("", response_model=UserRead, status_code=201, summary="新建用户")
def create_user(payload: UserCreate, session: DbSession, _: AdminGuard) -> UserRead:
    if user_repo.get_by_username(session, payload.username) is not None:
        raise BusinessError(USERNAME_DUPLICATE, detail={"username": payload.username}, http_status=409)

    unknown = [name for name in payload.roles if name not in permission_service.ROLE_PERMISSIONS]
    if unknown:
        raise BusinessError(ROLE_NOT_FOUND, detail={"roles": unknown}, http_status=404)

    user = user_repo.create(
        session,
        username=payload.username,
        hashed_password=hash_password(payload.password),
        email=payload.email,
        full_name=payload.full_name,
        phone=payload.phone,
        roles=permission_service.roles_for(session, payload.roles or ["operator"]),
    )
    session.commit()
    return UserRead.from_user(user)


@router.get("/{user_id}", response_model=UserRead, summary="用户详情")
def get_user(user_id: int, session: DbSession, _: AdminGuard) -> UserRead:
    user = user_repo.get(session, user_id)
    if user is None:
        raise BusinessError(USER_NOT_FOUND, http_status=404)
    return UserRead.from_user(user)


@router.patch("/{user_id}", response_model=UserRead, summary="更新用户")
def update_user(user_id: int, payload: UserUpdate, session: DbSession, _: AdminGuard) -> UserRead:
    user = user_repo.get(session, user_id)
    if user is None:
        raise BusinessError(USER_NOT_FOUND, http_status=404)

    changes = payload.model_dump(exclude_unset=True)
    if "roles" in changes and changes["roles"] is not None:
        unknown = [n for n in changes["roles"] if n not in permission_service.ROLE_PERMISSIONS]
        if unknown:
            raise BusinessError(ROLE_NOT_FOUND, detail={"roles": unknown}, http_status=404)
        permission_service.assign_roles(session, user, changes.pop("roles"))

    for field, value in changes.items():
        if value is not None:
            setattr(user, field, value)
    session.commit()
    return UserRead.from_user(user)


def _load(session: Session, user_id: int) -> User:  # pragma: no cover - helper
    user = user_repo.get(session, user_id)
    if user is None:
        raise BusinessError(USER_NOT_FOUND, http_status=404)
    return user
