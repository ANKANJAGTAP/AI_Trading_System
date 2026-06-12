"""Backtest performance metrics — the canonical implementation (the live dashboard's
`api/analytics.py` computes the same quantities; this is the shared math for research).
"""
from __future__ import annotations

import statistics as st


def compute_metrics(trades: list[dict], starting_capital: float) -> dict:
    """trades: dicts with at least pnl, r_multiple, ts. Returns KPIs + curves."""
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy_R": 0.0,
                "net_pnl": 0.0, "return_pct": 0.0, "max_dd": 0.0, "sharpe": 0.0,
                "largest_win": 0.0, "largest_loss": 0.0,
                "equity_curve": [], "drawdown_curve": []}

    pnls = [float(t["pnl"]) for t in trades]
    rmults = [float(t["r_multiple"]) for t in trades if t.get("r_multiple") is not None]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    gross_w, gross_l = sum(wins), abs(sum(losses))

    equity, drawdown, cum, peak = [], [], 0.0, 0.0
    for t in trades:
        cum += float(t["pnl"])
        equity.append({"ts": t.get("ts"), "value": round(cum, 2)})
        peak = max(peak, cum)
        drawdown.append({"ts": t.get("ts"), "value": round(cum - peak, 2)})
    max_dd = round(min((p["value"] for p in drawdown), default=0.0), 2)

    sharpe = 0.0
    if len(rmults) > 1 and st.pstdev(rmults):
        sharpe = round(st.mean(rmults) / st.pstdev(rmults), 2)

    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "profit_factor": round(gross_w / gross_l, 2) if gross_l else (999.0 if gross_w else 0.0),
        "expectancy_R": round(sum(rmults) / len(rmults), 3) if rmults else 0.0,
        "net_pnl": round(sum(pnls), 2),
        "return_pct": round(sum(pnls) / starting_capital * 100, 2) if starting_capital else 0.0,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "largest_win": round(max(wins), 2) if wins else 0.0,
        "largest_loss": round(min(losses), 2) if losses else 0.0,
        "equity_curve": equity,
        "drawdown_curve": drawdown,
    }
