"""Channel delivery implementations.

Every module here exposes the same ``deliver(session, *, notification_id,
endpoint, **fields) -> (status, response_code, error)`` signature so
:mod:`app.services.notification_service` can dispatch without knowing which
channel it is talking to.
"""

from app.services.channels import email, inapp, webhook

__all__ = ["email", "inapp", "webhook"]
