"""Candle + tick persistence and retrieval (TimescaleDB).

Single source of truth for the candle upsert (used by both the historical
backfill and the live aggregator) and a pandas loader for the indicator layer.
"""
from __future__ import annotations

import asyncio
import json

import asyncpg
import pandas as pd

from common.db import fetch, get_pool
from common.logging import get_logger

log = get_logger("store")

_UPSERT_CANDLE = """
INSERT INTO candles (ts, instrument_token, interval, open, high, low, close, volume, oi)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
ON CONFLICT (instrument_token, interval, ts) DO UPDATE SET
    open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
    close = EXCLUDED.close, volume = EXCLUDED.volume, oi = EXCLUDED.oi
"""

_INSERT_TICK = """
INSERT INTO ticks (ts, instrument_token, last_price, last_quantity, average_price,
                   volume, buy_quantity, sell_quantity, oi, bid, ask, raw)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb)
"""


async def upsert_candles(rows: list[tuple]) -> int:
    """rows: (ts, token, interval, open, high, low, close, volume, oi).

    Retries on deadlock — the live feed and a concurrent gap-reconcile/backfill can
    both upsert the same candle rows during market hours.
    """
    if not rows:
        return 0
    pool = await get_pool()
    for attempt in range(3):
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.executemany(_UPSERT_CANDLE, rows)
            return len(rows)
        except asyncpg.exceptions.DeadlockDetectedError:
            if attempt == 2:
                raise
            log.warning("candle_upsert_deadlock_retry", attempt=attempt + 1)
            await asyncio.sleep(0.1 * (attempt + 1))
    return len(rows)


async def insert_ticks(rows: list[dict]) -> int:
    """Optional raw-tick archive. rows are normalised tick dicts."""
    if not rows:
        return 0
    pool = await get_pool()
    payload = [
        (
            r["ts"], r["instrument_token"], r.get("last_price"), r.get("last_quantity"),
            r.get("average_price"), r.get("volume"), r.get("buy_quantity"),
            r.get("sell_quantity"), r.get("oi"), r.get("bid"), r.get("ask"),
            json.dumps(r.get("raw")) if r.get("raw") is not None else None,
        )
        for r in rows
    ]
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_INSERT_TICK, payload)
    return len(rows)


async def load_candles_df(instrument_token: int, interval: str, limit: int = 500) -> pd.DataFrame:
    """Most recent `limit` candles as a tz-aware, ascending OHLCV DataFrame."""
    rows = await fetch(
        "SELECT ts, open, high, low, close, volume, oi FROM candles "
        "WHERE instrument_token = $1 AND interval = $2 ORDER BY ts DESC LIMIT $3",
        instrument_token, interval, limit,
    )
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "oi"])
    df = pd.DataFrame([dict(r) for r in reversed(rows)]).set_index("ts")
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].fillna(0).astype("int64")
    return df


async def load_candles_range_df(instrument_token: int, interval: str, from_dt, to_dt) -> pd.DataFrame:
    """Ascending OHLCV frame for [from_dt, to_dt] — used by the backtester to preload a
    full window into memory and slice it point-in-time."""
    rows = await fetch(
        "SELECT ts, open, high, low, close, volume, oi FROM candles "
        "WHERE instrument_token = $1 AND interval = $2 AND ts >= $3 AND ts <= $4 ORDER BY ts",
        instrument_token, interval, from_dt, to_dt,
    )
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "oi"])
    df = pd.DataFrame([dict(r) for r in rows]).set_index("ts")
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].fillna(0).astype("int64")
    return df
