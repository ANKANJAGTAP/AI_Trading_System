"""Parameter-sweep validity report (§4 #26/#27) — pure, no I/O.

Running a strategy across a grid of parameters and keeping the in-sample best is
exactly how a backtest gets overfit. This turns a finished sweep into an honest
verdict: each config's Sharpe (the trial distribution), the best config's
Probabilistic Sharpe, the Deflated Sharpe (penalised for how many configs were
tried), and the PBO across CSCV splits.

Everything here is pure: the caller runs the real backtests (DB-coupled) and hands
the result dicts to `report_from_results`, so the verdict logic is fully unit-tested
without market data. `align_period_returns` puts every config on the same daily
period index (0 on days it didn't trade) so PBO compares like with like.
"""
from __future__ import annotations

from collections import defaultdict

from backtest.validation import (deflated_sharpe_ratio, pbo_cscv,
                                  probabilistic_sharpe_ratio, sharpe_ratio)


def daily_returns_from_trades(trades: list[dict], starting_capital: float) -> list[float]:
    """Bucket a single config's trade P&L by calendar day -> daily return series
    (day P&L / starting capital), ordered by date."""
    cap = starting_capital or 1.0
    by_day: dict[str, float] = defaultdict(float)
    for t in trades:
        by_day[str(t.get("ts", ""))[:10]] += float(t.get("pnl", 0.0))
    return [by_day[d] / cap for d in sorted(by_day)]


def align_period_returns(per_config_trades: dict[str, list[dict]],
                         starting_capital: float) -> dict[str, list[float]]:
    """Each config's trades -> a daily return series aligned on the UNION of all
    configs' trading days (0.0 on days a config didn't trade), so every series shares
    one period index and PBO compares configs over identical periods."""
    cap = starting_capital or 1.0
    per_day: dict[str, dict[str, float]] = {}
    all_days: set[str] = set()
    for label, trades in per_config_trades.items():
        d: dict[str, float] = defaultdict(float)
        for t in trades:
            d[str(t.get("ts", ""))[:10]] += float(t.get("pnl", 0.0))
        per_day[label] = d
        all_days |= set(d)
    days = sorted(all_days)
    return {label: [per_day[label].get(day, 0.0) / cap for day in days]
            for label in per_config_trades}


def _verdict(dsr: float, pbo: float) -> str:
    """A real edge needs a high deflated Sharpe AND a low overfitting probability —
    either one failing is disqualifying."""
    if dsr >= 0.95 and pbo <= 0.2:
        return "robust"
    if dsr <= 0.5 or pbo >= 0.5:
        return "likely_overfit"
    return "inconclusive"


def sweep_validation_report(per_config_returns: dict[str, list[float]],
                            n_splits: int = 10) -> dict:
    """`per_config_returns`: {config_label: [period_return, ...]}. Series are aligned
    to their common length. Returns the best config and the overfitting verdict."""
    labels = [k for k, v in per_config_returns.items() if v]
    if len(labels) < 2:
        return {"configs": len(labels), "verdict": "insufficient_configs"}
    length = min(len(per_config_returns[k]) for k in labels)
    if length < 2:
        return {"configs": len(labels), "verdict": "insufficient_history"}
    series = [per_config_returns[k][:length] for k in labels]

    trial_sharpes = [sharpe_ratio(s) for s in series]
    best_i = max(range(len(labels)), key=lambda i: trial_sharpes[i])
    matrix = [[series[c][t] for c in range(len(labels))] for t in range(length)]
    pbo = pbo_cscv(matrix, n_splits=n_splits)
    dsr = deflated_sharpe_ratio(series[best_i], trial_sharpes)

    return {
        "configs": len(labels),
        "periods": length,
        "best_config": labels[best_i],
        "best_sharpe": round(trial_sharpes[best_i], 4),
        "best_psr": round(probabilistic_sharpe_ratio(series[best_i]), 4),
        "deflated_sharpe": round(dsr, 4),
        "pbo": round(pbo["pbo"], 4),
        "n_splits": pbo["n_splits"],
        "verdict": _verdict(dsr, pbo["pbo"]),
    }


def report_from_results(per_config_results: dict[str, dict], starting_capital: float,
                        n_splits: int = 10) -> dict:
    """Convenience: take {config_label: backtest_result_dict} (each with a "trades"
    list), align to a common daily period index, and produce the sweep verdict."""
    per_config_trades = {label: res.get("trades", [])
                         for label, res in per_config_results.items()}
    aligned = align_period_returns(per_config_trades, starting_capital)
    return sweep_validation_report(aligned, n_splits=n_splits)
