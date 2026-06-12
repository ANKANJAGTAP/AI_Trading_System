"""Walk-forward validation (the honesty gate before trusting any backtest).

Splits the window into sequential time folds and runs the backtest on each. The
question it answers is the one that separates a real edge from a lucky period:
*is the expectancy consistent across time, or did one fold carry the whole result?*
A strategy that's +0.3R in one fold and -0.3R in the others has no edge — it has
variance. Also reports whether each fold independently shows feature lift.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from backtest.engine import BacktestParams, run_backtest


async def walk_forward(params: BacktestParams, folds: int = 4, cfg=None) -> dict:
    span = (params.to_dt - params.from_dt).days
    if folds < 2 or span < folds * 7:
        return {"error": "need >= 2 folds and a wide enough window"}
    step = span // folds
    fold_reports = []
    for k in range(folds):
        f_from = params.from_dt + timedelta(days=k * step)
        f_to = params.from_dt + timedelta(days=(k + 1) * step) if k < folds - 1 else params.to_dt
        res = await run_backtest(replace(params, from_dt=f_from, to_dt=f_to), cfg)
        m = res.get("metrics", {})
        disc = res.get("discrimination", {})
        fold_reports.append({
            "fold": k + 1, "from": str(f_from), "to": str(f_to),
            "trades": m.get("trades", 0), "net_pnl": m.get("net_pnl", 0.0),
            "expectancy_R": m.get("expectancy_R", 0.0), "win_rate": m.get("win_rate", 0.0),
            "profit_factor": m.get("profit_factor", 0.0),
            "top_feature": (disc.get("features") or [{}])[0].get("feature"),
            "top_lift": (disc.get("features") or [{}])[0].get("lift"),
        })

    exps = [f["expectancy_R"] for f in fold_reports if f["trades"] > 0]
    positive = sum(1 for e in exps if e > 0)
    import statistics as st
    mean_exp = round(st.mean(exps), 3) if exps else 0.0
    std_exp = round(st.pstdev(exps), 3) if len(exps) > 1 else 0.0
    # Stable + positive across folds => candidate edge. Mixed sign => variance, not edge.
    verdict = ("consistent_positive" if positive == len(exps) and len(exps) >= 2 and mean_exp > 0 else
               "consistent_negative" if positive == 0 and len(exps) >= 2 else
               "inconsistent")
    return {"folds": fold_reports,
            "summary": {"folds_evaluated": len(exps), "folds_positive": positive,
                        "mean_expectancy_R": mean_exp, "expectancy_stdev": std_exp,
                        "verdict": verdict}}
