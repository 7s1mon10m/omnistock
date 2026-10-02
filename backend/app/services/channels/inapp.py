"""In-app delivery: a notification row already *is* the delivery.

The in-app channel is the one case where "sending" is really just bookkeeping —
the message is already queryable via ``GET /notifications``.  Recording a
``sent`` delivery keeps the audit trail uniform across all three channels
instead of leaving in-app looking like it silently did nothing.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.models.notification import DeliveryStatus, NotificationChannel


def deliver(
    session: Session,
    *,
    notification_id: int,
    endpoint: str = "",
    **_kwargs,
) -> tuple[DeliveryStatus, int | None, str]:
    """Returns ``(status, response_code, error)``."""
    return DeliveryStatus.SENT, 200, ""
