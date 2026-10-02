"""SMTP delivery.

Refuses loudly when SMTP is not configured (business code 42402) rather than
silently swallowing the message — a "successful" notification that nobody
received is worse than a visible error.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import EMAIL_NOT_CONFIGURED, BusinessError
from app.models.notification import DeliveryStatus


def is_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM)


def require_config() -> None:
    if not is_configured():
        raise BusinessError(EMAIL_NOT_CONFIGURED, http_status=424)


def deliver(
    session: Session,  # noqa: ARG001 - uniform channel signature
    *,
    notification_id: int,
    endpoint: str,
    title: str = "",
    body: str = "",
    **_kwargs,
) -> tuple[DeliveryStatus, int | None, str]:
    require_config()

    message = EmailMessage()
    message["Subject"] = title or "OmniStock 通知"
    message["From"] = settings.SMTP_FROM
    message["To"] = endpoint
    message.set_content(body or title)

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        # 归一成一行，别把可能含收件人地址的原始异常塞进 ledger。
        return DeliveryStatus.RETRYING, None, f"{type(exc).__name__}: {exc}"[:200]

    return DeliveryStatus.SENT, 250, ""
