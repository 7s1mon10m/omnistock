"""Low-stock scan, runnable as a one-shot or from cron.

::

    python -m app.tasks.alert_scanner            # 扫描 + 生成补货建议
    python -m app.tasks.alert_scanner --warehouse 1

Deployment should run this from cron / a systemd timer using
``ALERT_SCAN_CRON`` rather than a resident process: a scan that dies silently
is worse than one that is obviously not running.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.db import SessionLocal, init_db
from app.services import alert_service, replenish_service


def run_once(warehouse_id: int | None = None, *, with_suggestions: bool = True) -> dict:
    init_db()
    session = SessionLocal()
    try:
        result = alert_service.scan(session, warehouse_id=warehouse_id)
        payload = {
            "scanned": result.scanned,
            "alerts_created": result.alerts_created,
            "alerts_skipped": result.alerts_skipped,
            "resolved": result.resolved,
            "notifications_sent": result.notifications_sent,
        }
        if with_suggestions:
            suggestions = replenish_service.generate(session, warehouse_id=warehouse_id)
            payload["suggestions_created"] = len(suggestions)
        return payload
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="库存预警扫描")
    parser.add_argument("--warehouse", type=int, default=None, help="只扫指定仓库")
    parser.add_argument(
        "--no-suggestions", action="store_true", help="只告警，不生成补货建议"
    )
    args = parser.parse_args(argv)

    payload = run_once(args.warehouse, with_suggestions=not args.no_suggestions)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
