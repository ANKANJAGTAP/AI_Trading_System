"""Venue-aware market sessions (P1#10).

Wraps the verified TradingCalendar (holidays) with per-venue intraday session
windows so the engine protects positions on the RIGHT clock — notably the MCX
evening session (to ~23:30), which the single equity window (09:15-15:30) left
under-managed. Pure + config-driven; no DB/Redis, so it unit-tests directly.
"""
from __future__ import annotations

import datetime as dt
from enum import Enum

from common.market_time import IST, parse_hhmm


class Venue(str, Enum):
    NSE_EQ = "NSE_EQ"
    NFO = "NFO"
    MCX = "MCX"


# Default intraday windows (IST). MCX runs an extended evening session.
_DEFAULT_WINDOWS: dict[Venue, tuple[str, str]] = {
    Venue.NSE_EQ: ("09:15", "15:30"),
    Venue.NFO: ("09:15", "15:30"),
    Venue.MCX: ("09:00", "23:30"),
}

_EXCHANGE_VENUE = {
    "NSE": Venue.NSE_EQ, "BSE": Venue.NSE_EQ,
    "NFO": Venue.NFO, "BFO": Venue.NFO,
    "MCX": Venue.MCX,
}


def venue_for(exchange: str | None, segment: str | None = None) -> Venue:
    """Map an instrument's exchange to its trading venue (defaults to NSE_EQ)."""
    return _EXCHANGE_VENUE.get((exchange or "").upper(), Venue.NSE_EQ)


class MarketSessions:
    def __init__(self, calendar=None, windows: dict | None = None):
        if calendar is None:
            from dataplatform.marketcalendar import TradingCalendar
            calendar = TradingCalendar.from_seed()
        self.calendar = calendar
        self.windows = {**_DEFAULT_WINDOWS, **(windows or {})}

    def is_open(self, venue: Venue, at: dt.datetime | None = None) -> bool:
        at = at or dt.datetime.now(IST)
        if not self.calendar.is_trading_day(at.date()):
            return False
        win = self.windows.get(venue)
        if not win:
            return False
        t = at.timetz().replace(tzinfo=None)
        return parse_hhmm(win[0]) <= t <= parse_hhmm(win[1])

    def any_open(self, at: dt.datetime | None = None) -> bool:
        """True if ANY venue is currently open — keeps the risk loop awake through
        the MCX evening, not just the equity window."""
        return any(self.is_open(v, at) for v in Venue)

    def open_venues(self, at: dt.datetime | None = None) -> list[Venue]:
        return [v for v in Venue if self.is_open(v, at)]
