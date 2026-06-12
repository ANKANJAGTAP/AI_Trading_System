"""Cross-sectional momentum portfolio backtest (the strategy class with real, durable,
documented retail edge — and the one the single-trade engines couldn't capture).

Each month: rank the universe by 6-month return (skipping the most recent month to dodge
short-term reversal — classic 12-1 / 6-1 momentum), keep only names above their 200-DMA,
hold the top-K equal-weighted, rebalance monthly. Low frequency => costs are amortised.
This is a PORTFOLIO/factor approach, not a single-trade signal — fundamentally different
from intraday/swing/F&O, and where cross-sectional alpha actually lives.

Compared head-to-head against an equal-weight buy-and-hold of the same universe so you
see whether the *ranking* adds value, not just the market beta.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from common.logging import get_logger
from data.instruments import resolve
from data.store import load_candles_range_df

log = get_logger("momentum_backtest")


def _metrics(monthly_rets: list[float], label: str) -> dict:
    if not monthly_rets:
        return {"label": label, "months": 0}
    r = np.array(monthly_rets, dtype=float)
    eq = np.cumprod(1.0 + r)
    total = eq[-1] - 1.0
    yrs = len(r) / 12.0
    cagr = (eq[-1]) ** (1 / yrs) - 1.0 if yrs > 0 and eq[-1] > 0 else -1.0
    peak = np.maximum.accumulate(eq)
    max_dd = float(((eq - peak) / peak).min())
    sharpe = float(r.mean() / r.std() * np.sqrt(12)) if r.std() else 0.0
    return {"label": label, "months": len(r), "total_return_pct": round(total * 100, 1),
            "cagr_pct": round(cagr * 100, 1), "max_dd_pct": round(max_dd * 100, 1),
            "sharpe": round(sharpe, 2)}


async def run_momentum(symbols, from_dt, to_dt, lookback: int = 126, skip: int = 21,
                       top_k: int = 5, cost_pct: float = 0.3) -> dict:
    warm = datetime.combine(from_dt - timedelta(days=400), datetime.min.time())
    end = datetime.combine(to_dt, datetime.max.time())
    closes = {}
    for s in symbols:
        inst = await resolve(s)
        if not inst:
            continue
        df = await load_candles_range_df(inst["instrument_token"], "day", warm, end)
        if not df.empty:
            closes[s] = df["close"].astype(float)
    if len(closes) < top_k + 1:
        return {"error": f"only {len(closes)} symbols resolved; need > {top_k}"}

    px = pd.DataFrame(closes).sort_index().ffill()
    if px.index.tz is not None:
        px.index = px.index.tz_convert("Asia/Kolkata").tz_localize(None)
    px_m = px.resample("ME").last()          # month-end prices
    sma200 = px.rolling(200).mean()
    dates = px_m.index

    mom_rets, bench_rets, picks_log = [], [], []
    prev = set()
    for k in range(len(dates) - 1):
        t, t1 = dates[k], dates[k + 1]
        if t < pd.Timestamp(from_dt):
            continue
        win = px[px.index <= t]
        if len(win) < lookback + skip + 1:
            continue
        # 6-month return ending one month ago (skip recent month)
        mom = win.iloc[-1 - skip] / win.iloc[-1 - skip - lookback] - 1.0
        above = win.iloc[-1] > sma200[sma200.index <= t].iloc[-1]
        eligible = mom[above].dropna().sort_values(ascending=False)
        picks = list(eligible.head(top_k).index)
        # forward 1-month return of the equal-weight selection (vs equal-weight all = benchmark)
        fwd = (px_m.loc[t1] / px_m.loc[t] - 1.0)
        port = float(fwd[picks].mean()) if picks else 0.0
        bench = float(fwd.mean())
        turnover = len(set(picks) ^ prev) / max(1, len(picks))
        mom_rets.append(port - turnover * cost_pct / 100.0)
        bench_rets.append(bench)
        prev = set(picks)
        picks_log.append({"date": str(t.date()), "picks": picks})

    return {"momentum": _metrics(mom_rets, "momentum_topK"),
            "benchmark": _metrics(bench_rets, "equal_weight_buy_hold"),
            "config": {"lookback_days": lookback, "skip_days": skip, "top_k": top_k,
                       "cost_pct": cost_pct, "universe": len(closes)},
            "last_picks": picks_log[-1] if picks_log else None}
