"""Client-side candle aggregator (spec §7).

Builds OHLCV candles for multiple intervals directly from the tick stream, with an
OI snapshot at close (F&O/MCX). A candle closes when a tick arrives in a later
bucket; closed candles are returned to the caller to persist immediately. The feed
also calls `flush()` at session end / before gap reconciliation.

Per-candle volume is derived from Kite's cumulative day volume:
    candle_volume = cum_volume(last tick) - cum_volume(first tick of bucket).
Candle `ts` is the bucket START (matching Kite historical's convention), so live
candles align with backfilled ones.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from common.market_time import IST

_INTERVAL_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15}


def bucket_start(ts: datetime, interval: str) -> datetime:
    ts = ts.astimezone(IST)
    if interval == "day":
        return ts.replace(hour=0, minute=0, second=0, microsecond=0)
    m = _INTERVAL_MINUTES[interval]
    return ts.replace(minute=(ts.minute // m) * m, second=0, microsecond=0)


@dataclass
class _Building:
    bucket_start: datetime
    open: float
    high: float
    low: float
    close: float
    vol_open: int
    volume: int
    oi: int | None


@dataclass
class ClosedCandle:
    ts: datetime
    instrument_token: int
    interval: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int | None

    def as_row(self) -> tuple:
        return (
            self.ts, self.instrument_token, self.interval,
            self.open, self.high, self.low, self.close, self.volume, self.oi,
        )


class CandleAggregator:
    def __init__(self, intervals: list[str]) -> None:
        self.intervals = [i for i in intervals if i in _INTERVAL_MINUTES or i == "day"]
        self._state: dict[tuple[int, str], _Building] = {}

    def add_tick(
        self,
        instrument_token: int,
        ts: datetime,
        last_price: float,
        cum_volume: int = 0,
        oi: int | None = None,
    ) -> list[ClosedCandle]:
        """Feed one tick; return any candles closed by it (across intervals)."""
        closed: list[ClosedCandle] = []
        for interval in self.intervals:
            bs = bucket_start(ts, interval)
            key = (instrument_token, interval)
            cur = self._state.get(key)
            if cur is None or bs > cur.bucket_start:
                if cur is not None:
                    closed.append(self._finalize(instrument_token, interval, cur))
                self._state[key] = _Building(
                    bucket_start=bs, open=last_price, high=last_price, low=last_price,
                    close=last_price, vol_open=cum_volume, volume=0, oi=oi,
                )
            else:
                cur.high = max(cur.high, last_price)
                cur.low = min(cur.low, last_price)
                cur.close = last_price
                # Cumulative day-volume can reset (new session) or step back after a
                # feed gap; re-anchor so this candle's volume never goes negative or
                # absorbs a stale baseline.
                if cum_volume < cur.vol_open:
                    cur.vol_open = cum_volume
                cur.volume = max(0, cum_volume - cur.vol_open)
                if oi is not None:
                    cur.oi = oi
        return closed

    def flush(self) -> list[ClosedCandle]:
        """Close and return all in-progress candles (session end / pre-reconcile)."""
        out = [self._finalize(tok, itv, c) for (tok, itv), c in self._state.items()]
        self._state.clear()
        return out

    @staticmethod
    def _finalize(token: int, interval: str, c: _Building) -> ClosedCandle:
        return ClosedCandle(
            ts=c.bucket_start, instrument_token=token, interval=interval,
            open=c.open, high=c.high, low=c.low, close=c.close, volume=c.volume, oi=c.oi,
        )
