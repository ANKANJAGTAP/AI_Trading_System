"""
Trading-day and holiday utilities.

Weekends are always non-trading. Exchange holidays are supplied as data (a set of
dates per exchange) — seed values are provided, but the authoritative list should
be loaded from the exchange holiday master each year. This is *reference data*, by
design: a holiday change is a data update, never a code change.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

# A small, clearly-marked seed of NSE/BSE trading holidays.
# NOTE: VERIFY & EXTEND from the official NSE/BSE holiday circular each year.
# Equity-derivatives holidays are (almost always) common to NSE & BSE.
_SEED_HOLIDAYS_COMMON: dict[int, list[str]] = {
    2024: [
        "2024-01-26", "2024-03-08", "2024-03-25", "2024-03-29", "2024-04-11",
        "2024-04-17", "2024-05-01", "2024-06-17", "2024-07-17", "2024-08-15",
        "2024-10-02", "2024-11-01", "2024-11-15", "2024-12-25",
    ],
    2025: [
        "2025-02-26", "2025-03-14", "2025-03-31", "2025-04-10", "2025-04-14",
        "2025-04-18", "2025-05-01", "2025-08-15", "2025-08-27", "2025-10-02",
        "2025-10-21", "2025-10-22", "2025-11-05", "2025-12-25",
    ],
    2026: [
        # SEED ONLY — replace with the official 2026 circular when published.
        "2026-01-26", "2026-03-06", "2026-03-25", "2026-04-01", "2026-04-14",
        "2026-05-01", "2026-08-15", "2026-10-02", "2026-11-09", "2026-12-25",
    ],
}


def _parse(d: str) -> dt.date:
    return dt.date.fromisoformat(d)


@dataclass
class TradingCalendar:
    """Holds holidays for an exchange and answers trading-day questions."""

    exchange: str = "NSE"
    holidays: set[dt.date] = field(default_factory=set)

    @classmethod
    def from_seed(cls, exchange: str = "NSE") -> "TradingCalendar":
        hols: set[dt.date] = set()
        for _yr, days in _SEED_HOLIDAYS_COMMON.items():
            hols.update(_parse(d) for d in days)
        return cls(exchange=exchange, holidays=hols)

    def add_holidays(self, days: list[str] | list[dt.date]) -> None:
        for d in days:
            self.holidays.add(_parse(d) if isinstance(d, str) else d)

    # --- core predicates -------------------------------------------------
    def is_weekend(self, d: dt.date) -> bool:
        return d.weekday() >= 5  # 5=Sat, 6=Sun

    def is_trading_day(self, d: dt.date) -> bool:
        return not self.is_weekend(d) and d not in self.holidays

    def previous_trading_day(self, d: dt.date) -> dt.date:
        cur = d - dt.timedelta(days=1)
        while not self.is_trading_day(cur):
            cur -= dt.timedelta(days=1)
        return cur

    def next_trading_day(self, d: dt.date) -> dt.date:
        cur = d + dt.timedelta(days=1)
        while not self.is_trading_day(cur):
            cur += dt.timedelta(days=1)
        return cur

    def roll_to_trading_day(self, d: dt.date) -> dt.date:
        """If d is a holiday/weekend, roll *back* to the previous trading day.

        This is the standard Indian-exchange rule for expiry that falls on a
        holiday: the contract expires on the previous trading day.
        """
        if self.is_trading_day(d):
            return d
        return self.previous_trading_day(d)

    def trading_days_between(self, start: dt.date, end: dt.date) -> int:
        """Count trading days in (start, end]  — useful for DTE context."""
        if end <= start:
            return 0
        n, cur = 0, start
        while cur < end:
            cur += dt.timedelta(days=1)
            if self.is_trading_day(cur):
                n += 1
        return n
