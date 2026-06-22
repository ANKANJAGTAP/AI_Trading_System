"""Pin risk + expiry-day position controls (§10 Phase 5) — pure, no I/O.

Near expiry a short option struck around the spot ('pinned') has exploding gamma and
assignment risk while theta collapses — the classic expiry-day blowup. This decides
allow / reduce / block by days-to-expiry, moneyness, and side, and flags pin risk for
ATM shorts so the engine can square them off in time.
"""
from __future__ import annotations

from datetime import date


def days_to_expiry(expiry: date, today: date | None = None) -> int:
    return (expiry - (today or date.today())).days


def moneyness(spot: float, strike: float) -> float:
    """Relative distance of strike from spot (0 = exactly ATM)."""
    return abs(spot - strike) / spot if spot else 1.0


def pin_risk(spot: float, strike: float, dte: int, *, atm_band: float = 0.01,
             dte_max: int = 1) -> bool:
    """True if a strike is ATM (within atm_band) at/near expiry — pin / assignment risk."""
    return dte <= dte_max and moneyness(spot, strike) <= atm_band


def expiry_action(dte: int, mny: float, is_short: bool, *, atm_band: float = 0.02) -> str:
    """allow | reduce | block. Expired -> block. An ATM short is blocked on expiry day
    (pin/assignment) and reduced the day before; longs are defined-risk so they pass."""
    if dte < 0:
        return "block"
    if is_short and mny <= atm_band:
        if dte == 0:
            return "block"
        if dte == 1:
            return "reduce"
    return "allow"
