"""Logging setup.

Two output modes: a readable line format for local development and one JSON
object per line for production, which is what collectors (Loki, ELK, journald
pipelines) expect. Both carry the request id so an access log line can be
joined with the application lines it produced.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar

from app.core.config import settings

#: Populated by the request-id middleware and read by the formatter.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_EXTRA_FIELDS = ("request_id", "method", "path", "status_code", "duration_ms", "client")


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.request_id = getattr(record, "request_id", None) or request_id_var.get()
        base = f"%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"
        formatter = logging.Formatter(base, datefmt="%Y-%m-%d %H:%M:%S")
        line = formatter.format(record)

        extras = [
            f"{field}={getattr(record, field)}"
            for field in _EXTRA_FIELDS
            if field != "request_id" and hasattr(record, field)
        ]
        if extras:
            line = f"{line} | {' '.join(extras)}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
        }
        for field in _EXTRA_FIELDS:
            if field == "request_id":
                continue
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def build_handler() -> logging.Handler:
    if settings.LOG_FILE:
        handler: logging.Handler = logging.FileHandler(settings.LOG_FILE, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.LOG_JSON else PlainFormatter())
    return handler


def setup_logging() -> None:
    """Configure the root logger once, at application import time."""
    handler = build_handler()
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.LOG_LEVEL.upper())

    # Access logs come from our own middleware, so keep uvicorn's from doubling up.
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).handlers = []
        logging.getLogger(noisy).propagate = settings.LOG_ACCESS is False

    for name in ("uvicorn", "uvicorn.error", "app"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(settings.LOG_LEVEL.upper())

    # SQLAlchemy echoes every statement at INFO; keep it at WARNING.
    logging.getLogger("sqlalchemy.engine").setLevel("WARNING")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
