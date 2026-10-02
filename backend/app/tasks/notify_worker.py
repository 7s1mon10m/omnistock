"""Notification delivery worker.

::

    python -m app.tasks.notify_worker              # 跑一轮就退出
    python -m app.tasks.notify_worker --loop       # 常驻，每 5 秒扫一次

Retry timing is stored on each delivery (``next_retry_at``), so stopping and
restarting the worker never loses or duplicates a retry: the schedule lives in
the database, not in the process.
"""

from __future__ import annotations

import argparse
import sys
import time

from app.db import SessionLocal, init_db
from app.services import notification_service


def run_once(limit: int = 50) -> int:
    init_db()
    session = SessionLocal()
    try:
        return notification_service.retry_due(session, limit=limit)
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="通知投递重试")
    parser.add_argument("--limit", type=int, default=50, help="单轮最多处理多少条")
    parser.add_argument("--loop", action="store_true", help="常驻运行")
    parser.add_argument("--interval", type=float, default=5.0, help="轮询间隔秒数")
    args = parser.parse_args(argv)

    if not args.loop:
        print(f"retried {run_once(args.limit)} deliveries")
        return 0

    while True:
        try:
            count = run_once(args.limit)
            if count:
                print(f"retried {count} deliveries")
        except KeyboardInterrupt:  # pragma: no cover - interactive
            return 0
        except Exception as exc:  # noqa: BLE001 - a worker must not die on one bad row
            print(f"worker error: {type(exc).__name__}: {exc}", file=sys.stderr)
        time.sleep(args.interval)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
