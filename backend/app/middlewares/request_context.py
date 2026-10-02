"""Request id propagation and access logging.

A raw ASGI middleware so it runs for every request, including ones rejected
before routing.  It echoes ``X-Request-ID`` back to the client, which makes a
user reported error traceable in the logs.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from app.core.config import settings
from app.core.logging import request_id_var

logger = logging.getLogger("app.access")

#: Requests to these paths are not written to the access log.
QUIET_PATHS = {"/healthz", "/readyz", "/metrics", "/favicon.ico"}


class RequestContextMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id")
        request_id = (incoming.decode("latin-1") if incoming else "") or uuid.uuid4().hex[:16]

        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 0
        path = scope.get("path", "")
        method = scope.get("method", "")

        async def inspecting_send(message):
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = message.get("status", 0)
                raw_headers = list(message.get("headers") or [])
                raw_headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": raw_headers}
            await send(message)

        try:
            await self.app(scope, receive, inspecting_send)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            if settings.LOG_ACCESS and path not in QUIET_PATHS:
                logger.info(
                    "%s %s -> %s",
                    method,
                    path,
                    status_code,
                    extra={
                        "request_id": request_id,
                        "method": method,
                        "path": path,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "client": (scope.get("client") or ["-"])[0],
                    },
                )
            request_id_var.reset(token)
