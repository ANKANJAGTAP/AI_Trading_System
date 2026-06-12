"""Historical candle backfill from Kite (spec §7).

Backfills the `candles` hypertable: initial deep history, nightly incremental
top-up, and on-reconnect gap reconciliation. Kite caps the date range per request
per interval, so requests are chunked by `max_days_per_request`. All Kite REST is
routed through the RateGovernor; persistence goes through data.store.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from common.db import fetchval
from common.logging import get_logger
from common.market_time import IST, now_ist
from data.store import upsert_candles

log = get_logger("historical")

# Canonical interval -> Kite historical interval name.
KITE_INTERVAL = {
    "1m": "minute",
    "3m": "3minute",
    "5m": "5minute",
    "15m": "15minute",
    "day": "day",
}


def _to_ist(dt: datetime) -> datetime:
    """Kite formats datetimes as wall-clock; pass IST so day boundaries align."""
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)


def _chunks(from_dt: datetime, to_dt: datetime, max_days: int):
    step = timedelta(days=max(1, max_days))
    cur = from_dt
    while cur < to_dt:
        end = min(cur + step, to_dt)
        yield cur, end
        cur = end


async def backfill(
    adapter,
    governor,
    instrument_token: int,
    interval: str,
    from_dt: datetime,
    to_dt: datetime,
    oi: bool = False,
    max_days: int = 60,
) -> int:
    """Backfill [from_dt, to_dt] for one instrument/interval; returns rows written."""
    from_dt, to_dt = _to_ist(from_dt), _to_ist(to_dt)
    kite_interval = KITE_INTERVAL.get(interval, interval)
    total = 0
    for start, end in _chunks(from_dt, to_dt, max_days):
        data = await governor.call(
            "historical", adapter.historical, instrument_token, start, end, kite_interval, False, oi
        )
        if not data:
            continue
        rows = [
            (
                c["date"], instrument_token, interval,
                c["open"], c["high"], c["low"], c["close"],
                int(c.get("volume") or 0), c.get("oi"),
            )
            for c in data
        ]
        total += await upsert_candles(rows)
    log.info("backfill_done", token=instrument_token, interval=interval, rows=total)
    return total


async def last_candle_ts(instrument_token: int, interval: str) -> datetime | None:
    return await fetchval(
        "SELECT max(ts) FROM candles WHERE instrument_token = $1 AND interval = $2",
        instrument_token, interval,
    )


async def incremental_backfill(
    adapter,
    governor,
    instrument_token: int,
    interval: str,
    lookback_days: int,
    max_days: int,
    oi: bool = False,
) -> int:
    """Top up from the last stored candle (or `lookback_days` back) to now."""
    to_dt = now_ist()
    last = await last_candle_ts(instrument_token, interval)
    from_dt = last if last else to_dt - timedelta(days=lookback_days)
    return await backfill(
        adapter, governor, instrument_token, interval, from_dt, to_dt, oi=oi, max_days=max_days
    )


async def reconcile_gap(
    adapter, governor, instrument_token: int, interval: str, max_days: int, oi: bool = False
) -> int:
    """Fill any gap between the last stored candle and now (post-reconnect)."""
    last = await last_candle_ts(instrument_token, interval)
    if last is None:
        return 0
    to_dt = now_ist()
    if last >= to_dt:
        return 0
    log.info("gap_reconcile", token=instrument_token, interval=interval, since=str(last))
    return await backfill(
        adapter, governor, instrument_token, interval, last, to_dt, oi=oi, max_days=max_days
    )
