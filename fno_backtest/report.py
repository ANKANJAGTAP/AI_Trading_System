"""
Canonical backtest report.

Keeps the repo's familiar metrics (win rate, profit factor, expectancy, max DD,
Sharpe-like) and adds a BIAS-AUDIT header so a reader can see which realism
guards were active — a report with guards disabled is "exploratory, not
promotable". Deflated-Sharpe / PBO live in ml.metrics and are fed the CPCV
distribution at promotion time.
"""
from __future__ import annotations

import numpy as np

from ml import metrics as M

_DEFAULT_AUDIT = {
    "lookahead_guard": True,
    "survivorship": "n/a (cash-settled index)",
    "worst_fill_default": True,
    "costs_modelled": True,
}


def build_report(result, num_trials: int = 1, bias_audit: dict | None = None) -> dict:
    trades = result.trades
    pnl = trades["net"].to_numpy() if len(trades) else np.array([])
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    eq = result.equity

    if len(eq) > 1:
        dd = float((eq / eq.cummax() - 1).min() * 100)
        trade_rets = pnl / result.starting_capital
        sharpe_like = M.sharpe_ratio(trade_rets, periods=len(trade_rets) or 1)
    else:
        dd, sharpe_like = 0.0, 0.0

    return {
        "n_trades": int(len(pnl)),
        "win_rate_pct": float((pnl > 0).mean() * 100) if len(pnl) else float("nan"),
        "profit_factor": M.profit_factor(pnl) if len(pnl) else float("nan"),
        "expectancy": float(pnl.mean()) if len(pnl) else float("nan"),
        "net_pnl": float(pnl.sum()),
        "return_pct": float((eq.iloc[-1] / result.starting_capital - 1) * 100) if len(eq) else 0.0,
        "max_drawdown_pct": dd,
        "sharpe_like": float(sharpe_like),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "total_costs": float(trades["costs"].sum()) if len(trades) else 0.0,
        "num_trials": num_trials,
        "bias_audit": {**_DEFAULT_AUDIT, **(bias_audit or {})},
    }
