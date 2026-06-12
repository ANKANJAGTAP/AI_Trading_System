"""Central rate-limit governor for all Kite REST calls (spec §7, mandatory).

- Token-bucket per endpoint class: quote / historical / order / other.
- 429 / TooManyRequests backoff-retry.
- Daily + per-minute order-count guard that alerts and halts new entries before
  the exchange cap is hit.

No component may call Kite REST directly outside this governor. KiteConnect's REST
client is synchronous, so the governor is async and runs each blocking call in a
worker thread — composing cleanly with the asyncio engine.

    governor = RateGovernor(config.data.rate_limits, alerter)
    insts = await governor.call("other", adapter.instruments)
    candles = await governor.call("historical", adapter.historical, token, ...)
"""
from __future__ import annotations

import asyncio
import datetime
import time
from dataclasses import dataclass, field

from common.logging import get_logger

log = get_logger("rate_governor")

try:  # keep import soft so unit tests don't need kiteconnect
    from kiteconnect.exceptions import TooManyRequestsException as _TooMany
except Exception:  # pragma: no cover
    class _TooMany(Exception):
        ...


@dataclass
class TokenBucket:
    """A simple async token bucket."""

    capacity: float
    refill_per_sec: float
    _tokens: float = field(init=False)
    _last: float = field(init=False)
    _lock: asyncio.Lock = field(init=False)

    def __post_init__(self) -> None:
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self.capacity, self._tokens + (now - self._last) * self.refill_per_sec
                )
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                wait = (tokens - self._tokens) / self.refill_per_sec
            # Sleep WITHOUT holding the lock so other callers can re-check/refill.
            await asyncio.sleep(wait)


class RateGovernor:
    def __init__(self, rate_limits: dict | None = None, alerter=None) -> None:
        rl = rate_limits or {}

        def bucket(name: str, cap: float, rate: float) -> TokenBucket:
            c = rl.get(name) or {}
            return TokenBucket(float(c.get("capacity", cap)), float(c.get("refill_per_sec", rate)))

        self.buckets = {
            "quote": bucket("quote", 1, 1),
            "historical": bucket("historical", 3, 3),
            "order": bucket("order", 8, 8),
            "other": bucket("other", 8, 8),
        }
        guard = rl.get("order_count_guard") or {}
        self.per_minute_cap = int(guard.get("per_minute_cap", 200))
        self.daily_cap = int(guard.get("daily_cap", 3000))
        self.alert_threshold_pct = float(guard.get("alert_threshold_pct", 80))
        self.alerter = alerter
        self.max_retries = 5

        self._order_times: list[float] = []
        self._daily_count = 0
        self._daily_date: datetime.date | None = None
        self._alerted_threshold = False

    def _bucket(self, endpoint_class: str) -> TokenBucket:
        return self.buckets.get(endpoint_class, self.buckets["other"])

    async def call(self, endpoint_class: str, fn, *args, **kwargs):
        """Throttle + execute a (blocking) Kite REST call with 429 backoff."""
        if endpoint_class == "order":
            self._check_order_guard()
        attempt = 0
        while True:
            await self._bucket(endpoint_class).acquire()
            try:
                result = await asyncio.to_thread(fn, *args, **kwargs)
                if endpoint_class == "order":
                    self._record_order()
                return result
            except _TooMany:
                attempt += 1
                if attempt > self.max_retries:
                    raise
                backoff = min(2 ** attempt, 30)
                log.warning(
                    "rate_limited_backoff", endpoint=endpoint_class,
                    attempt=attempt, sleep=backoff,
                )
                await asyncio.sleep(backoff)

    # --- order-count guard -------------------------------------------------
    def _roll_day(self) -> None:
        today = datetime.date.today()
        if self._daily_date != today:
            self._daily_date = today
            self._daily_count = 0
            self._order_times.clear()
            self._alerted_threshold = False

    def _check_order_guard(self) -> None:
        self._roll_day()
        now = time.monotonic()
        self._order_times = [t for t in self._order_times if now - t < 60]
        if self._daily_count >= self.daily_cap or len(self._order_times) >= self.per_minute_cap:
            detail = (
                f"daily={self._daily_count}/{self.daily_cap}, "
                f"minute={len(self._order_times)}/{self.per_minute_cap}"
            )
            log.error("order_cap_reached_halt", detail=detail)
            if self.alerter:
                self.alerter.send("Order cap reached — halting new entries", detail)
            raise RuntimeError(f"Order rate cap reached — new entries halted ({detail})")

    def _record_order(self) -> None:
        self._daily_count += 1
        self._order_times.append(time.monotonic())
        threshold = self.daily_cap * self.alert_threshold_pct / 100
        if self._daily_count >= threshold and not self._alerted_threshold:
            self._alerted_threshold = True
            log.warning("approaching_daily_order_cap", count=self._daily_count, cap=self.daily_cap)
            if self.alerter:
                self.alerter.send(
                    "Approaching daily order cap",
                    f"{self._daily_count}/{self.daily_cap} orders today",
                )
