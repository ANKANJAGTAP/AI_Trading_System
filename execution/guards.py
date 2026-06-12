"""Fast-loop risk guards (spec §1 fast loop / §8). Pure, sub-millisecond price
checks: stop-loss, target, trailing stop, and hard square-off time. Re-armed on
cold-start recovery; driven by the tick loop in Phase 5.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from common.market_time import IST, parse_hhmm
from execution.models import ExitReason, ExitSignal


@dataclass
class Guard:
    position_id: int
    side: str                       # BUY (long) / SELL (short)
    entry: float
    stop: float
    target: float = 0.0
    instrument_token: int = 0
    trail_distance: float | None = None   # e.g. ATR multiple; None disables trailing
    square_off: str | None = None         # "HH:MM" hard exit; None disables
    high_water: float = field(default=0.0)
    # Dynamic profit protection (config strategy.<sleeve>.dynamic_exit): the stop
    # RATCHETS as the trade works — a winner is never allowed to become a loser,
    # and a near-target trade never round-trips its gain.
    breakeven_at_r: float = 0.0     # gain >= this many R -> stop moves to entry (0=off)
    lock_trigger_frac: float = 0.0  # gain >= this fraction of target distance ...
    max_giveback_frac: float = 0.35 # ... -> stop trails to keep (1-this) of peak gain
    init_risk: float = 0.0          # original |entry - stop| (the R unit), set at arm
    best_gain: float = field(default=0.0)

    def check(self, price: float, now: datetime | None = None) -> ExitSignal | None:
        now = now or datetime.now(IST)
        long = self.side == "BUY"

        if self.square_off:
            if now.timetz().replace(tzinfo=None) >= parse_hhmm(self.square_off):
                return ExitSignal(ExitReason.TIME, price)

        if self.trail_distance:
            if long:
                self.high_water = max(self.high_water or self.entry, price)
                self.stop = max(self.stop, self.high_water - self.trail_distance)
            else:
                self.high_water = min(self.high_water or self.entry, price)
                self.stop = min(self.stop, self.high_water + self.trail_distance)

        # --- dynamic profit protection (stop only ever tightens) -------------
        gain = (price - self.entry) if long else (self.entry - price)
        if gain > self.best_gain:
            self.best_gain = gain
        if self.init_risk <= 0:
            self.init_risk = abs(self.entry - self.stop)
        if self.breakeven_at_r and self.init_risk > 0 \
                and self.best_gain >= self.breakeven_at_r * self.init_risk:
            self.stop = max(self.stop, self.entry) if long else min(self.stop, self.entry)
        if self.lock_trigger_frac and self.target:
            tdist = abs(self.target - self.entry)
            if tdist > 0 and self.best_gain >= self.lock_trigger_frac * tdist:
                keep = self.best_gain * (1.0 - self.max_giveback_frac)
                lock = (self.entry + keep) if long else (self.entry - keep)
                self.stop = max(self.stop, lock) if long else min(self.stop, lock)

        if long:
            if price <= self.stop:
                return ExitSignal(ExitReason.STOP, price)
            if self.target and price >= self.target:
                return ExitSignal(ExitReason.TARGET, price)
        else:
            if price >= self.stop:
                return ExitSignal(ExitReason.STOP, price)
            if self.target and price <= self.target:
                return ExitSignal(ExitReason.TARGET, price)
        return None


class GuardManager:
    def __init__(self) -> None:
        self.guards: dict[int, Guard] = {}
        self._by_token: dict[int, set[int]] = {}

    def arm(self, guard: Guard) -> None:
        self.guards[guard.position_id] = guard
        self._by_token.setdefault(guard.instrument_token, set()).add(guard.position_id)

    def disarm(self, position_id: int) -> None:
        guard = self.guards.pop(position_id, None)
        if guard is not None:
            ids = self._by_token.get(guard.instrument_token)
            if ids:
                ids.discard(position_id)

    def process(self, position_id: int, price: float, now: datetime | None = None) -> ExitSignal | None:
        guard = self.guards.get(position_id)
        return guard.check(price, now) if guard else None

    def for_token(self, instrument_token: int) -> list[int]:
        return list(self._by_token.get(instrument_token, set()))

    def armed_ids(self) -> list[int]:
        return list(self.guards)
