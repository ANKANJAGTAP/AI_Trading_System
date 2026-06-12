"""Per-instrument ATM IV history + IV Rank/Percentile (Phase 2.2).

A nightly job records each F&O underlying's ATM IV; the F&O pipeline then reads a
REAL per-name IV Rank instead of the single INDIA VIX proxy. The ranking math reuses
the (already-tested) pure functions in data/options.py.
"""
from __future__ import annotations

from common.db import execute, fetch
from common.market_time import today_ist
from data.options import iv_percentile, iv_rank


def rank_from_history(history: list[float]) -> float | None:
    """IV Rank of the latest point within its history (pure; testable)."""
    if not history or len(history) < 2:
        return None
    return iv_rank(history[-1], history)


def percentile_from_history(history: list[float]) -> float | None:
    if not history or len(history) < 2:
        return None
    return iv_percentile(history[-1], history)


async def record_atm_iv(name: str, atm_iv: float, day=None) -> None:
    await execute(
        "INSERT INTO iv_history (name, ts, atm_iv) VALUES ($1,$2,$3) "
        "ON CONFLICT (name, ts) DO UPDATE SET atm_iv = EXCLUDED.atm_iv",
        name, day or today_ist(), atm_iv)


async def atm_iv_history(name: str, lookback: int = 250) -> list[float]:
    rows = await fetch(
        "SELECT atm_iv FROM iv_history WHERE name=$1 ORDER BY ts DESC LIMIT $2", name, lookback)
    return [float(r["atm_iv"]) for r in reversed(rows) if r["atm_iv"] is not None]


async def iv_rank_for(name: str, lookback: int = 250, min_points: int = 20) -> float | None:
    """Per-name IV Rank (0-100), or None when there isn't enough history yet (the
    caller then falls back to the INDIA VIX proxy)."""
    hist = await atm_iv_history(name, lookback)
    if len(hist) < min_points:
        return None
    return rank_from_history(hist)


def change_from_history(history: list[float], days: int = 5) -> float:
    """% change of the latest IV vs `days` snapshots ago (pure; testable).
    0.0 when there isn't enough history — the caller must fail OPEN, not block."""
    if len(history) < days + 1 or history[-(days + 1)] <= 0:
        return 0.0
    return (history[-1] - history[-(days + 1)]) / history[-(days + 1)] * 100.0


async def iv_change_for(name: str, days: int = 5) -> float:
    """Recent IV momentum (%) for the vol-direction guard: selling credit on a high
    IV LEVEL is fine; selling into a vol SPIKE (level high *because* it's exploding)
    is how short-vol accounts die. Best-effort: 0.0 without enough history."""
    hist = await atm_iv_history(name, days + 5)
    return change_from_history(hist, days)
