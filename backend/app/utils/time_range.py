"""Half-open time interval helpers used by the scheduler.

A booking occupies ``[start, end)``; two bookings conflict only when the
intervals actually overlap, so one ending at 10:00 and another starting at
10:00 are fine.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class TimeRange:
    start: dt.datetime
    end: dt.datetime

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("结束时间必须晚于开始时间")

    @property
    def duration_minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60

    def overlaps(self, other: "TimeRange") -> bool:
        return self.start < other.end and other.start < self.end

    def overlap_with(self, other: "TimeRange") -> "TimeRange | None":
        """Return the intersecting interval, or ``None`` when there is none."""
        if not self.overlaps(other):
            return None
        return TimeRange(max(self.start, other.start), min(self.end, other.end))

    def contains(self, moment: dt.datetime) -> bool:
        return self.start <= moment < self.end

    def minutes_until_start(self, now: dt.datetime) -> float:
        return (self.start - now).total_seconds() / 60

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def day_bounds(day: dt.date) -> TimeRange:
    """Midnight-to-midnight range for a calendar day."""
    start = dt.datetime.combine(day, dt.time.min)
    return TimeRange(start, start + dt.timedelta(days=1))


def week_bounds(day: dt.date) -> TimeRange:
    """Monday-to-next-Monday range containing ``day``."""
    monday = day - dt.timedelta(days=day.weekday())
    start = dt.datetime.combine(monday, dt.time.min)
    return TimeRange(start, start + dt.timedelta(days=7))
