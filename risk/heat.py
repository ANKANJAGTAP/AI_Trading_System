"""Portfolio heat & correlation tracking (spec §4).

Heat = total open R vs the portfolio risk limit. Correlation clusters are derived
from real daily-return correlation of the open positions' candles (data-driven,
no external sector feed) — >2 mutually correlated positions count as concentrated
risk the operator should see.
"""
from __future__ import annotations

import pandas as pd

from common.logging import get_logger
from data.store import load_candles_df
from risk.models import HeatSnapshot
from risk.positions import deployed_by_sleeve, open_trades_count, total_open_r
from risk.sizing import max_concurrent_positions

log = get_logger("heat")


async def _correlation_clusters(positions: list[dict], threshold: float, lookback: int) -> list[list[str]]:
    series: dict[str, pd.Series] = {}
    for p in positions:
        df = await load_candles_df(p["instrument_token"], "day", lookback)
        if len(df) >= 30:
            series[p["tradingsymbol"]] = df["close"].pct_change().dropna()
    if len(series) < 3:  # need >2 to form a concentrated cluster
        return []
    matrix = pd.DataFrame(series).dropna()
    if len(matrix) < 20:
        return []
    corr = matrix.corr()
    symbols = list(corr.columns)
    visited: set[str] = set()
    clusters: list[list[str]] = []
    for s in symbols:
        if s in visited:
            continue
        group = [s] + [t for t in symbols if t != s and t not in visited and corr.loc[s, t] >= threshold]
        if len(group) > 2:
            clusters.append(group)
            visited.update(group)
    return clusters


async def compute_heat(config, positions: list[dict], capital: float,
                       per_trade_pct: float | None = None) -> HeatSnapshot:
    """`per_trade_pct` is the EFFECTIVE per-trade R% (paper overlay when active) so
    max-concurrent reflects what the sizing actually enforces. Positions are counted
    as TRADES (a structure's legs share one correlation_id = one slot)."""
    pr_limit_pct = config.risk.portfolio_risk_limit_pct.default
    pr_limit_r = pr_limit_pct / 100.0 * capital
    open_r = total_open_r(positions)
    ks = config.risk.kill_switch or {}
    clusters = await _correlation_clusters(
        positions,
        float(ks.get("correlation_threshold", 0.7)),
        int(ks.get("correlation_lookback", 120)),
    )
    return HeatSnapshot(
        total_open_r=open_r,
        portfolio_risk_limit_r=pr_limit_r,
        heat_pct=(open_r / pr_limit_r * 100.0) if pr_limit_r > 0 else 0.0,
        num_open_positions=open_trades_count(positions),
        max_concurrent_positions=max_concurrent_positions(
            pr_limit_pct, per_trade_pct or config.risk.per_trade_risk_pct.default
        ),
        correlated_clusters=clusters,
        by_sleeve=deployed_by_sleeve(positions),
    )
