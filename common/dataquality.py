"""#29 Market-data quality gate — pure validators (no I/O).

A tick that fails any check should not update indicators or trigger entries; the
caller flags the symbol and skips it. Kept pure so it's trivially testable and
safe to call from the hot path.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TickCheck:
    ok: bool
    reason: str = "ok"


def validate_tick(price, *, prev_price=None, ts_age_s=None, bid=None, ask=None,
                  volume=None, max_age_s: float = 30.0,
                  max_jump_pct: float = 0.20) -> TickCheck:
    """Reject zero/negative price, stale timestamp, crossed/invalid bid-ask, an
    unrealistic jump vs the previous price, or negative volume."""
    if price is None or price <= 0:
        return TickCheck(False, "non-positive price")
    if ts_age_s is not None and ts_age_s > max_age_s:
        return TickCheck(False, f"stale tick ({ts_age_s:.0f}s > {max_age_s:.0f}s)")
    if bid is not None and ask is not None:
        if bid <= 0 or ask <= 0:
            return TickCheck(False, "non-positive bid/ask")
        if bid > ask:
            return TickCheck(False, "crossed book (bid > ask)")
    if prev_price is not None and prev_price > 0:
        jump = abs(price - prev_price) / prev_price
        if jump > max_jump_pct:
            return TickCheck(False, f"price jump {jump:.1%} > {max_jump_pct:.0%}")
    if volume is not None and volume < 0:
        return TickCheck(False, "negative volume")
    return TickCheck(True, "ok")
