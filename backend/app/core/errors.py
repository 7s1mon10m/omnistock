"""Unified error model.

Every failure the API reports uses the same envelope so a client can branch on
a stable business code instead of a prose message::

    {"code": 40901, "message": "...", "detail": {...}}

The first three digits of a business code mirror the HTTP status it maps to.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# ------------------------------------------------------------------ auth (401xx)
AUTH_INVALID_CREDENTIALS = 40101
AUTH_TOKEN_EXPIRED = 40102
AUTH_ACCOUNT_LOCKED = 40103
AUTH_TOKEN_INVALID = 40104

# ------------------------------------------------------------ permission (403xx)
PERMISSION_DENIED = 40301

# ------------------------------------------------------------- not found (404xx)
USER_NOT_FOUND = 40401
ROLE_NOT_FOUND = 40402
SPU_NOT_FOUND = 40410
SKU_NOT_FOUND = 40411
WAREHOUSE_NOT_FOUND = 40412
LOCATION_NOT_FOUND = 40413
BUNDLE_NOT_FOUND = 40414

# -------------------------------------------------------------- conflict (409xx)
SPU_CODE_DUPLICATE = 40901
SKU_CODE_DUPLICATE = 40902
BARCODE_DUPLICATE = 40903
INVENTORY_CONCURRENT_CONFLICT = 40904
ADJUST_REASON_REQUIRED = 40905
INSUFFICIENT_STOCK = 40906
BUNDLE_COMPONENT_INVALID = 40907
WAREHOUSE_CODE_DUPLICATE = 40908
LOCATION_CODE_DUPLICATE = 40909
USERNAME_DUPLICATE = 40920

# ------------------------------------------------------------ bad request (400xx)
INVENTORY_ADJUST_ZERO_DELTA = 40010
BUNDLE_CANNOT_NEST = 40011
SKU_STATUS_INVALID = 40012
SPU_TYPE_NOT_BUNDLE = 40013

DEFAULT_MESSAGES = {
    AUTH_INVALID_CREDENTIALS: "用户名或密码不正确",
    AUTH_TOKEN_EXPIRED: "登录已过期，请重新登录",
    AUTH_ACCOUNT_LOCKED: "连续登录失败次数过多，账号已临时锁定",
    AUTH_TOKEN_INVALID: "令牌无效",
    PERMISSION_DENIED: "当前角色没有执行该操作的权限",
    USER_NOT_FOUND: "用户不存在",
    ROLE_NOT_FOUND: "角色不存在",
    SPU_NOT_FOUND: "商品不存在",
    SKU_NOT_FOUND: "SKU 不存在",
    WAREHOUSE_NOT_FOUND: "仓库不存在",
    LOCATION_NOT_FOUND: "库位不存在",
    BUNDLE_NOT_FOUND: "组合商品不存在",
    SPU_CODE_DUPLICATE: "商品编码已存在",
    SKU_CODE_DUPLICATE: "SKU 编码已存在",
    BARCODE_DUPLICATE: "条码已被占用",
    INVENTORY_CONCURRENT_CONFLICT: "库存被并发修改，请重试",
    ADJUST_REASON_REQUIRED: "库存调整必须填写原因",
    INSUFFICIENT_STOCK: "可售库存不足",
    BUNDLE_COMPONENT_INVALID: "组合商品的子项不合法",
    WAREHOUSE_CODE_DUPLICATE: "仓库编码已存在",
    LOCATION_CODE_DUPLICATE: "库位编码已存在",
    USERNAME_DUPLICATE: "用户名已存在",
    INVENTORY_ADJUST_ZERO_DELTA: "调整数量不能为 0",
    BUNDLE_CANNOT_NEST: "组合商品不能嵌套其他组合商品",
    SKU_STATUS_INVALID: "SKU 状态不允许该操作",
    SPU_TYPE_NOT_BUNDLE: "该商品不是组合商品类型，请先创建 type=bundle 的商品",
}


class BusinessError(Exception):
    """Domain error carrying a stable business code."""

    def __init__(
        self,
        code: int,
        message: str | None = None,
        http_status: int | None = None,
        detail: Any = None,
    ) -> None:
        self.code = code
        self.message = message or DEFAULT_MESSAGES.get(code, "请求失败")
        self.detail = detail
        # The first three digits of the business code mirror the HTTP status.
        self.http_status = http_status or (code // 1000 if code >= 10000 else 400)
        if self.http_status not in (400, 401, 403, 404, 409, 422, 424, 500, 503):
            self.http_status = 400
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


def _error_response(status: int, code: int, message: str, detail: Any = None) -> JSONResponse:
    payload: dict[str, Any] = {"code": code, "message": message}
    if detail is not None:
        payload["detail"] = detail
    return JSONResponse(status_code=status, content=payload)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach handlers that normalise every error into the common envelope."""

    @app.exception_handler(BusinessError)
    async def _business(request: Request, exc: BusinessError) -> JSONResponse:  # noqa: ARG001
        return _error_response(exc.http_status, exc.code, exc.message, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:  # noqa: ARG001
        return _error_response(
            422,
            42201,
            "请求参数校验失败",
            [{"field": ".".join(str(p) for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()],
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
        return _error_response(500, 50000, "服务器内部错误")
