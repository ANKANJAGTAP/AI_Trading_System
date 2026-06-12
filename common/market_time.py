"""Time helpers anchored to IST (Asia/Kolkata)."""
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def parse_hhmm(value: str) -> time:
    """Parse 'HH:MM' into a time."""
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def is_within(window_start: str, window_end: str, at: datetime | None = None) -> bool:
    """Whether `at` (IST) falls within an inclusive HH:MM..HH:MM window."""
    at = at or now_ist()
    t = at.timetz().replace(tzinfo=None)
    return parse_hhmm(window_start) <= t <= parse_hhmm(window_end)
