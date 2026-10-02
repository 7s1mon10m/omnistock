"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.deps import CurrentUser, DbSession
from app.core.errors import AUTH_INVALID_CREDENTIALS, BusinessError
from app.core.security import hash_password, verify_password
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    TokenPair,
)
from app.schemas.common import OkResponse
from app.schemas.user import UserRead
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse, summary="账号密码登录")
def login(payload: LoginRequest, request: Request, session: DbSession) -> LoginResponse:
    tokens, user = auth_service.login(
        session,
        payload.username,
        payload.password,
        user_agent=request.headers.get("user-agent", "")[:255],
    )
    return LoginResponse(**tokens.model_dump(), user=user)


@router.post("/refresh", response_model=TokenPair, summary="用刷新令牌换取新的令牌对")
def refresh(payload: RefreshRequest, session: DbSession) -> TokenPair:
    return auth_service.refresh(session, payload.refresh_token)


@router.post("/logout", response_model=OkResponse, summary="注销当前刷新令牌")
def logout(payload: RefreshRequest, session: DbSession) -> OkResponse:
    auth_service.logout(session, payload.refresh_token)
    return OkResponse(ok=True, message="已退出登录")


@router.get("/me", response_model=UserRead, summary="当前登录者信息")
def me(user: CurrentUser) -> UserRead:
    return UserRead.from_user(user)


@router.post("/change-password", response_model=OkResponse, summary="修改当前用户密码")
def change_password(
    payload: ChangePasswordRequest, session: DbSession, user: CurrentUser
) -> OkResponse:
    if not verify_password(payload.old_password, user.hashed_password):
        raise BusinessError(AUTH_INVALID_CREDENTIALS, "原密码不正确", http_status=401)
    user.hashed_password = hash_password(payload.new_password)
    session.flush()
    auth_service.revoke_all(session, user.id)
    session.commit()
    return OkResponse(ok=True, message="密码已更新，请重新登录")
