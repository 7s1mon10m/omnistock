"""Webhook delivery via HTTP POST.

Uses ``urllib`` from the standard library so a small deployment needs no extra
dependency.  A 5xx or a transport error is retryable; a 4xx is not — retrying a
rejected payload just burns the budget, so 4xx fails immediately.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.notification import DeliveryStatus

#: 4xx 是「对方明确拒绝」，重试没有意义。
NON_RETRYABLE = 400


def deliver(
    session: Session,  # noqa: ARG001 - uniform channel signature
    *,
    notification_id: int,
    endpoint: str,
    title: str = "",
    body: str = "",
    level: str = "info",
    **_kwargs,
) -> tuple[DeliveryStatus, int | None, str]:
    if not endpoint:
        return DeliveryStatus.SKIPPED, None, "未配置 Webhook 地址"

    payload = json.dumps(
        {
            "notification_id": notification_id,
            "title": title,
            "body": body,
            "level": level,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request, timeout=settings.WEBHOOK_TIMEOUT_SECONDS
        ) as response:
            code = int(response.status)
    except urllib.error.HTTPError as exc:
        code = int(exc.code)
        if 400 <= code < 500:
            return DeliveryStatus.FAILED, code, f"HTTP {code}"
        return DeliveryStatus.RETRYING, code, f"HTTP {code}"
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return DeliveryStatus.RETRYING, None, f"{type(exc).__name__}: {exc}"[:200]

    if 200 <= code < 300:
        return DeliveryStatus.SENT, code, ""
    if 400 <= code < 500:
        return DeliveryStatus.FAILED, code, f"HTTP {code}"
    return DeliveryStatus.RETRYING, code, f"HTTP {code}"
