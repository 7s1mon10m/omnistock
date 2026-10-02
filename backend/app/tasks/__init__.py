"""Background entry points.

These are plain CLI modules rather than a task framework on purpose: a small
deployment schedules them with cron, and a scan that is not running is
immediately visible in the scheduler's logs.
"""

__all__ = ["alert_scanner", "notify_worker"]
