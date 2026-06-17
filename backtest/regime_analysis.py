"""Regime-bucketed performance + parameter-decay kill criteria (#26) — pure, no I/O.

Two questions every honest backtest must answer beyond a single Sharpe:
  1. WHERE does the edge live? Bucketing trade outcomes by market regime exposes a
     strategy that only works in (say) trending tape and bleeds in chop.
  2. Is the edge DECAYING? Comparing a recent window's expectancy to the earlier
     baseline catches a strategy whose edge has been arbitraged away — and gives a
     written-in-advance kill rule rather than hoping it comes back.
"""
from __future__ import annotations

from collections import defaultdict

_REGIME_KEYS = ("regime", "intraday_regime", "market_regime")


def _trade_regime(t: dict, key: str | None) -> str:
    feats = t.get("features") or {}
    if key:
        return str(t.get(key, feats.get(key, "unknown")))
    for k in _REGIME_KEYS:
        if k in t:
            return str(t[k])
        if k in feats:
            return str(feats[k])
    return "unknown"


def bucket_by_regime(trades: list[dict], regime_key: str | None = None) -> dict:
    """Group trade R-multiples by regime tag -> per-bucket trades/expectancy/win-rate.
    A bucket with negative expectancy is where the strategy is actually losing."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        r = t.get("r_multiple")
        if r is None:
            continue
        buckets[_trade_regime(t, regime_key)].append(float(r))
    out = {}
    for name, rs in buckets.items():
        wins = sum(1 for r in rs if r > 0)
        out[name] = {
            "trades": len(rs),
            "expectancy_R": round(sum(rs) / len(rs), 3),
            "win_rate": round(wins / len(rs) * 100, 1),
            "total_R": round(sum(rs), 3),
        }
    return out


def parameter_decay(period_expectancies: list[float], *, recent: int = 3,
                    drop_frac: float = 0.5) -> dict:
    """Compare the recent window's mean expectancy to the earlier baseline. `kill` when
    the recent window turns negative, or falls more than `drop_frac` below a positive
    baseline (edge decayed past the pre-committed line)."""
    n = len(period_expectancies)
    if n < recent + 1:
        return {"decaying": False, "kill": False, "reason": "insufficient history",
                "recent": None, "baseline": None}
    recent_vals = period_expectancies[-recent:]
    baseline_vals = period_expectancies[:-recent]
    r_mean = sum(recent_vals) / len(recent_vals)
    b_mean = sum(baseline_vals) / len(baseline_vals)
    kill = r_mean < 0 or (b_mean > 0 and r_mean < b_mean * (1.0 - drop_frac))
    decaying = r_mean < b_mean
    return {
        "decaying": decaying,
        "kill": kill,
        "recent": round(r_mean, 3),
        "baseline": round(b_mean, 3),
        "drop_frac": round((b_mean - r_mean) / b_mean, 3) if b_mean > 0 else None,
        "reason": ("recent expectancy negative" if r_mean < 0 else
                   "recent fell past decay threshold" if kill else
                   "stable" if not decaying else "softening"),
    }
