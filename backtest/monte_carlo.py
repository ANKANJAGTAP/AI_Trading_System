"""Bootstrap / Monte-Carlo on trade returns (§10 Phase 3) — pure (stdlib random).

The historical equity curve is one sample path; resampling per-trade returns with
replacement builds the DISTRIBUTION of outcomes it can't show — terminal-P&L
percentiles, worst drawdown, and risk-of-ruin. Seeded for deterministic tests.
"""
from __future__ import annotations

import random
import statistics as st


def bootstrap_paths(returns: list[float], horizon: int, n_paths: int = 1000,
                    seed: int = 0) -> list[tuple]:
    """n_paths simulated paths, each a cumulative sum of `horizon` resampled returns.
    Returns [(terminal_pnl, max_drawdown)] (max_drawdown <= 0)."""
    rs = list(returns)
    if not rs or horizon <= 0 or n_paths <= 0:
        return []
    rng = random.Random(seed)
    out = []
    for _ in range(n_paths):
        cum = peak = maxdd = 0.0
        for _ in range(horizon):
            cum += rng.choice(rs)
            peak = max(peak, cum)
            maxdd = min(maxdd, cum - peak)
        out.append((cum, maxdd))
    return out


def _pct(sorted_xs: list[float], q: float) -> float:
    if not sorted_xs:
        return 0.0
    return round(sorted_xs[min(len(sorted_xs) - 1, int(q * len(sorted_xs)))], 4)


def summary(returns: list[float], horizon: int, n_paths: int = 1000, seed: int = 0) -> dict:
    """Distribution summary over the simulated paths."""
    paths = bootstrap_paths(returns, horizon, n_paths, seed)
    if not paths:
        return {"paths": 0}
    terminals = sorted(p[0] for p in paths)
    dds = sorted(p[1] for p in paths)
    return {
        "paths": len(paths),
        "terminal_p05": _pct(terminals, 0.05),
        "terminal_p50": _pct(terminals, 0.50),
        "terminal_p95": _pct(terminals, 0.95),
        "terminal_mean": round(st.mean(terminals), 4),
        "worst_drawdown_p05": _pct(dds, 0.05),    # a deep (5th-percentile) drawdown
        "median_drawdown": _pct(dds, 0.50),
    }


def risk_of_ruin(returns: list[float], horizon: int, ruin_threshold: float,
                 n_paths: int = 1000, seed: int = 0) -> float:
    """Fraction of paths whose running drawdown breaches -|ruin_threshold| (ruin)."""
    paths = bootstrap_paths(returns, horizon, n_paths, seed)
    if not paths:
        return 0.0
    ruined = sum(1 for _, maxdd in paths if maxdd <= -abs(ruin_threshold))
    return round(ruined / len(paths), 4)
