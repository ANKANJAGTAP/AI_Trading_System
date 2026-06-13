"""
Risk analysis for the backtester:

  * monte_carlo_paths — bootstrap the trade-sequence to get a DISTRIBUTION of
    terminal P&L and max drawdown, exposing path risk a single equity curve hides.
  * scenario_grid     — reprice an option structure over a spot x IV grid (BS),
    because Greeks make linear VaR misleading for options.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from features.options import bs_price


def monte_carlo_paths(trade_pnls, n_paths: int = 2000, seed: int = 0) -> dict:
    pnl = np.asarray(trade_pnls, dtype=float)
    if pnl.size == 0:
        return {}
    rng = np.random.default_rng(seed)
    terminals = np.empty(n_paths)
    maxdds = np.empty(n_paths)
    for i in range(n_paths):
        sample = rng.choice(pnl, size=pnl.size, replace=True)
        eq = np.cumsum(sample)
        peak = np.maximum.accumulate(eq)
        terminals[i] = eq[-1]
        maxdds[i] = (eq - peak).min()
    return {
        "terminal_mean": float(terminals.mean()),
        "terminal_p05": float(np.percentile(terminals, 5)),
        "terminal_p95": float(np.percentile(terminals, 95)),
        "maxdd_mean": float(maxdds.mean()),
        "maxdd_worst_p05": float(np.percentile(maxdds, 5)),
        "prob_profit": float((terminals > 0).mean()),
    }


def scenario_grid(structure, spot: float, t: float, r: float = 0.065,
                  iv: float = 0.2, spot_shocks=None, iv_shocks=None) -> pd.DataFrame:
    """MTM P&L of `structure` over a spot x IV grid (rows=spot, cols=IV)."""
    spot_shocks = np.linspace(-0.07, 0.07, 7) if spot_shocks is None else np.asarray(spot_shocks)
    iv_shocks = np.linspace(-0.05, 0.10, 4) if iv_shocks is None else np.asarray(iv_shocks)

    grid = []
    for ds in spot_shocks:
        S = spot * (1 + ds)
        row = []
        for dv in iv_shocks:
            sig = max(iv + dv, 1e-4)
            mtm = 0.0
            for leg in structure.legs:
                price = S if leg.opt_type == "FUT" else bs_price(S, leg.strike, t, r, sig, leg.opt_type)
                per_unit = (price - leg.entry_price) if leg.side.upper() == "BUY" \
                    else (leg.entry_price - price)
                mtm += per_unit * leg.qty
            row.append(mtm)
        grid.append(row)
    return pd.DataFrame(
        grid,
        index=[round(spot * (1 + d), 2) for d in spot_shocks],
        columns=[round(iv + d, 4) for d in iv_shocks],
    )
