"""Audit trail for write operations.

Runs as a middleware so no endpoint has to remember to log itself — a
hand-written audit call is an audit call that will be forgotten on the next
endpoint.

Deliberately narrow:

* only mutating verbs (POST/PUT/PATCH/DELETE) are recorded;
* only **successful** writes (2xx) — a rejected attempt changed nothing, and
  logging every failed login attempt here would drown the useful signal;
* login and token refresh are skipped: they have their own trail, and token
  responses would put credentials in a table anyone can query.
"""

from __future__ import annotations

import json
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from app.core.config import settings
from app.db import SessionLocal
from app.services import audit_service

logger = logging.getLogger("app.audit")

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
#: 认证相关端点不进审计：登录有自己的链路，且把令牌响应写进一张可查询的表
#: 等于把凭据存了下来。登出也不记 —— 它没有改变任何业务数据。
SKIP_PATHS = (
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/change-password",
    "/api/v1/auth/logout",
)

#: First path segment after the version prefix, used as the resource type.
VERSION_PREFIX = "/api/v1/"


class AuditMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method not in MUTATING:
            return await call_next(request)
        if not request.url.path.startswith(VERSION_PREFIX):
            return await call_next(request)
        if any(request.url.path.startswith(path) for path in SKIP_PATHS):
            return await call_next(request)

        # Read the body *before* the handler, then hand the same bytes back:
        # consuming the stream here would leave the endpoint with an empty body
        # and turn every write into a 422 that never gets audited.
        body = await self._read_body(request)
        receive = _replay(request, body)

        started = time.perf_counter()
        response = await self._call(request, call_next, receive)
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        if 200 <= response.status_code < 300:
            self._write(request, response.status_code, body, elapsed_ms)
        return response

    @staticmethod
    async def _call(request: Request, call_next, receive):
        """Invoke the next handler with a receive channel that replays the body."""
        scope = dict(request.scope)
        return await call_next(Request(scope, receive))

    @staticmethod
    async def _read_body(request: Request) -> bytes:
        try:
            return await request.body()
        except Exception:  # noqa: BLE001 - a broken body must not break the request
            return b""

    @staticmethod
    def _write(request: Request, status_code: int, body: bytes, elapsed_ms: int) -> None:
        path = request.url.path
        actor_id = getattr(request.state, "user_id", None)
        actor_name = getattr(request.state, "username", "") or ""

        try:
            session = SessionLocal()
            try:
                audit_service.record(
                    session,
                    actor_id=actor_id,
                    actor_name=actor_name,
                    action=audit_service.action_for(request.method, path),
                    resource_type=audit_service.resource_type_for(path),
                    resource_id=_resource_id(path),
                    method=request.method,
                    path=path,
                    status_code=status_code,
                    ip=request.client.host if request.client else "",
                    user_agent=request.headers.get("user-agent", "")[:255],
                    request_id=getattr(request.state, "request_id", "") or "",
                    summary=f"{request.method} {path} -> {status_code} ({elapsed_ms}ms)",
                    detail={"elapsed_ms": elapsed_ms},
                    payload_preview=audit_service.sanitize_preview(_preview(body)),
                )
                session.commit()
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001 - auditing must never break the request
            logger.warning("写入审计日志失败：%s", exc)


def _replay(request: Request, body: bytes):
    """A receive channel that yields the captured body again, then EOF."""
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


def _resource_type(path: str) -> str:
    rest = path[len(VERSION_PREFIX) :] if path.startswith(VERSION_PREFIX) else path
    return (rest.split("/")[0] if rest else "")[:48]


def _resource_id(path: str) -> str:
    """The last path segment, when it looks like an identifier."""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return ""
    last = parts[-1]
    return last[:48] if last.isdigit() else ""


def _preview(body: bytes) -> str:
    if not body:
        return ""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return "<二进制内容>"
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    if isinstance(parsed, dict):
        parsed.pop("password", None)
    return json.dumps(parsed, ensure_ascii=False)
