"""
Point-in-time F&O expiry engine.

Indian index-derivative expiry rules have changed repeatedly (weekly launches,
the 2024 FinNifty-weekly discontinuation, multiple expiry-weekday shifts in
2025-26). Hard-coding any of this silently corrupts a 15-20 year backtest, so
expiry rules are modelled as **effective-dated reference data** and resolved
*as of the simulated date*.

The ENGINE here (last-weekday, holiday rollback, point-in-time selection) is
exact and tested. The RULE TABLE below contains structural facts that are
certain (weekly-availability windows, the last-<weekday> monthly scheme) plus
expiry-WEEKDAY values that you must VERIFY against the official NSE/BSE
circulars — they are flagged `verify=True`. Updating a rule is a data edit.
"""
from __future__ import annotations

import calendar as _cal
import datetime as dt
from dataclasses import dataclass

from .holidays import TradingCalendar

# Weekday constants (Python: Monday=0 .. Sunday=6)
MON, TUE, WED, THU, FRI = 0, 1, 2, 3, 4


# --------------------------------------------------------------------------- #
# Weekday math
# --------------------------------------------------------------------------- #
def last_weekday_of_month(year: int, month: int, weekday: int) -> dt.date:
    """Return the date of the LAST given weekday in (year, month)."""
    last_dom = _cal.monthrange(year, month)[1]
    d = dt.date(year, month, last_dom)
    offset = (d.weekday() - weekday) % 7
    return d - dt.timedelta(days=offset)


def weekdays_in_range(start: dt.date, end: dt.date, weekday: int) -> list[dt.date]:
    """All dates in [start, end] falling on `weekday` (unadjusted)."""
    out: list[dt.date] = []
    # advance to first matching weekday
    cur = start + dt.timedelta(days=(weekday - start.weekday()) % 7)
    while cur <= end:
        out.append(cur)
        cur += dt.timedelta(days=7)
    return out


# --------------------------------------------------------------------------- #
# Effective-dated expiry rules
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ExpiryRule:
    underlying: str
    valid_from: dt.date
    valid_to: dt.date | None          # None = still in force
    has_weekly: bool
    weekly_weekday: int | None        # None when has_weekly is False
    monthly_weekday: int              # monthly = last <weekday> of month
    note: str = ""
    verify: bool = True               # weekday values to be confirmed vs circular

    def active_on(self, d: dt.date) -> bool:
        if d < self.valid_from:
            return False
        return self.valid_to is None or d <= self.valid_to


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


# Verified facts (sources: NSE/BSE circulars & reporting, 2019-2026):
#   - NIFTY weekly options launched Feb 2019; monthly-only before that.
#   - EXPIRY DAYS SWAPPED effective 2025-09-01: NSE moved Nifty weekly+monthly
#     from Thursday -> TUESDAY; BSE moved Sensex -> THURSDAY.
#   - FINNIFTY weekly DISCONTINUED (last weekly 2024-11-19) -> monthly-only.
#   - SENSEX (BSE) weekly launched May 2023 (Friday); later Tuesday; now Thursday.
# verify=True marks weekday/boundary values still to confirm against circulars.
SEED_EXPIRY_RULES: list[ExpiryRule] = [
    # ---------------- NIFTY (NSE) ----------------
    ExpiryRule("NIFTY", _d("2001-06-01"), _d("2019-02-10"),
               has_weekly=False, weekly_weekday=None, monthly_weekday=THU,
               note="Pre-weekly era: monthly-only, last Thursday.", verify=False),
    ExpiryRule("NIFTY", _d("2019-02-11"), _d("2025-08-31"),
               has_weekly=True, weekly_weekday=THU, monthly_weekday=THU,
               note="Weekly + monthly on Thursday.", verify=False),
    ExpiryRule("NIFTY", _d("2025-09-01"), None,
               has_weekly=True, weekly_weekday=TUE, monthly_weekday=TUE,
               note="CURRENT: weekly+monthly on TUESDAY (NSE/BSE swap eff 2025-09-01).",
               verify=False),

    # ---------------- FINNIFTY (NSE) ----------------
    ExpiryRule("FINNIFTY", _d("2021-01-11"), _d("2024-11-19"),
               has_weekly=True, weekly_weekday=TUE, monthly_weekday=TUE,
               note="Weekly era: weekly + monthly on Tuesday.", verify=False),
    ExpiryRule("FINNIFTY", _d("2024-11-20"), _d("2025-08-31"),
               has_weekly=False, weekly_weekday=None, monthly_weekday=THU,
               note="Weekly discontinued; monthly-only. Monthly weekday (Thu) "
                    "follows the NSE common cycle of the time — VERIFY.", verify=True),
    ExpiryRule("FINNIFTY", _d("2025-09-01"), None,
               has_weekly=False, weekly_weekday=None, monthly_weekday=TUE,
               note="Monthly-only; aligned to current NSE Tuesday cycle — VERIFY.",
               verify=True),

    # ---------------- SENSEX (BSE) ----------------
    ExpiryRule("SENSEX", _d("2000-06-01"), _d("2023-05-14"),
               has_weekly=False, weekly_weekday=None, monthly_weekday=FRI,
               note="Pre active-weekly era (BSE), monthly-only.", verify=True),
    ExpiryRule("SENSEX", _d("2023-05-15"), _d("2024-12-31"),
               has_weekly=True, weekly_weekday=FRI, monthly_weekday=FRI,
               note="BSE Sensex weekly launched May 2023 on Friday. End-date approx — VERIFY.",
               verify=True),
    ExpiryRule("SENSEX", _d("2025-01-01"), _d("2025-08-31"),
               has_weekly=True, weekly_weekday=TUE, monthly_weekday=TUE,
               note="Interim: Sensex weekly on Tuesday before the swap. Boundary approx — VERIFY.",
               verify=True),
    ExpiryRule("SENSEX", _d("2025-09-01"), None,
               has_weekly=True, weekly_weekday=THU, monthly_weekday=THU,
               note="CURRENT: Sensex weekly+monthly on THURSDAY (swap eff 2025-09-01).",
               verify=False),
]


class ExpiryResolver:
    """Resolves weekly/monthly expiries as-of any historical date."""

    def __init__(
        self,
        rules: list[ExpiryRule] | None = None,
        calendars: dict[str, TradingCalendar] | None = None,
    ):
        self.rules = rules if rules is not None else list(SEED_EXPIRY_RULES)
        # one calendar per exchange; default to a shared seed calendar
        self.calendars = calendars or {}
        self._default_cal = TradingCalendar.from_seed()

    # -- internals --------------------------------------------------------
    def _cal_for(self, underlying: str) -> TradingCalendar:
        from ..config import EXCHANGE_OF
        exch = EXCHANGE_OF.get(underlying, "NSE")
        return self.calendars.get(exch, self._default_cal)

    def rule_on(self, underlying: str, asof: dt.date) -> ExpiryRule:
        for r in self.rules:
            if r.underlying == underlying and r.active_on(asof):
                return r
        raise ValueError(f"No expiry rule for {underlying} as of {asof}")

    # -- monthly ----------------------------------------------------------
    def monthly_expiry(self, underlying: str, year: int, month: int) -> dt.date:
        """Adjusted monthly expiry date for a given contract month."""
        rule = self.rule_on(underlying, dt.date(year, month, 15))
        raw = last_weekday_of_month(year, month, rule.monthly_weekday)
        return self._cal_for(underlying).roll_to_trading_day(raw)

    def current_monthly_expiry(self, underlying: str, asof: dt.date) -> dt.date:
        """The monthly expiry of the front contract that is still open on `asof`."""
        exp = self.monthly_expiry(underlying, asof.year, asof.month)
        if exp >= asof:
            return exp
        # rolled into next month
        ny, nm = (asof.year + 1, 1) if asof.month == 12 else (asof.year, asof.month + 1)
        return self.monthly_expiry(underlying, ny, nm)

    # -- weekly -----------------------------------------------------------
    def has_weekly(self, underlying: str, asof: dt.date) -> bool:
        return self.rule_on(underlying, asof).has_weekly

    def next_weekly_expiry(self, underlying: str, asof: dt.date) -> dt.date | None:
        """Nearest weekly expiry (adjusted) on/after `asof`, or None if the
        underlying has no weekly contract in that regime."""
        rule = self.rule_on(underlying, asof)
        if not rule.has_weekly or rule.weekly_weekday is None:
            return None
        cal = self._cal_for(underlying)
        # scan up to ~5 weeks of candidate weekly dates
        for raw in weekdays_in_range(asof, asof + dt.timedelta(days=40),
                                     rule.weekly_weekday):
            adj = cal.roll_to_trading_day(raw)
            if adj >= asof:
                return adj
        return None

    # -- generic ----------------------------------------------------------
    def expiries_in_range(
        self, underlying: str, start: dt.date, end: dt.date, kind: str = "all"
    ) -> list[dict]:
        """List expiries between start and end (inclusive).

        kind: 'weekly' | 'monthly' | 'all'. Each item:
        {date, type}. Monthly takes precedence when a date is both.
        """
        out: dict[dt.date, str] = {}

        # monthly
        y, m = start.year, start.month
        while dt.date(y, m, 1) <= end:
            try:
                exp = self.monthly_expiry(underlying, y, m)
                if start <= exp <= end:
                    out[exp] = "monthly"
            except ValueError:
                pass
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)

        # weekly
        if kind in ("weekly", "all"):
            cur = start
            while cur <= end:
                if self.has_weekly(underlying, cur):
                    w = self.next_weekly_expiry(underlying, cur)
                    if w is not None and start <= w <= end:
                        out.setdefault(w, "weekly")
                    cur = (w + dt.timedelta(days=1)) if w else cur + dt.timedelta(days=7)
                else:
                    cur += dt.timedelta(days=7)

        if kind == "monthly":
            out = {d: t for d, t in out.items() if t == "monthly"}
        elif kind == "weekly":
            # keep dates that are weekly OR monthly-coinciding? expose weekly set only
            out = {d: t for d, t in out.items()}

        return [{"date": d, "type": out[d]} for d in sorted(out)]

    def days_to_expiry(self, underlying: str, asof: dt.date, expiry: dt.date) -> int:
        """Trading days from `asof` to `expiry` (calendar-aware DTE context)."""
        return self._cal_for(underlying).trading_days_between(asof, expiry)
