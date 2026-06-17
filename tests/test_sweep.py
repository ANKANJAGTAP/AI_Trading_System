"""Tests for the parameter-sweep validity report + PSR wired into compute_metrics."""
from backtest.metrics import compute_metrics
from backtest.sweep import (align_period_returns, daily_returns_from_trades,
                            report_from_results, sweep_validation_report)


# ----------------------------------------------------- daily returns / alignment
def test_daily_returns_from_trades_buckets_by_day():
    trades = [
        {"ts": "2026-01-01T10:00", "pnl": 1000.0},
        {"ts": "2026-01-01T11:00", "pnl": -500.0},
        {"ts": "2026-01-02T10:00", "pnl": 2000.0},
    ]
    out = daily_returns_from_trades(trades, 100_000)
    assert out == [0.005, 0.02]                       # (500/100k, 2000/100k), date-ordered


def test_align_period_returns_unions_days_and_zero_fills():
    per_cfg = {
        "A": [{"ts": "2026-01-01", "pnl": 1000.0}, {"ts": "2026-01-02", "pnl": 1000.0}],
        "B": [{"ts": "2026-01-02", "pnl": 2000.0}, {"ts": "2026-01-03", "pnl": 2000.0}],
    }
    aligned = align_period_returns(per_cfg, 100_000)
    assert len(aligned["A"]) == len(aligned["B"]) == 3          # union {d1,d2,d3}
    assert aligned["A"] == [0.01, 0.01, 0.0]                    # no trade on d3 -> 0
    assert aligned["B"] == [0.0, 0.02, 0.02]                    # no trade on d1 -> 0


# ----------------------------------------------------- sweep verdict
def test_sweep_insufficient_configs():
    assert sweep_validation_report({"A": [0.1, 0.2]})["verdict"] == "insufficient_configs"


def test_sweep_insufficient_history():
    out = sweep_validation_report({"A": [0.1], "B": [0.2]})
    assert out["verdict"] == "insufficient_history"


def test_sweep_robust_for_dominant_config():
    per_cfg = {
        "A": [0.02 + (0.001 if i % 2 else -0.001) for i in range(40)],  # mean .02, tiny vol
        "B": [(0.01 if i % 2 else -0.01) for i in range(40)],           # mean 0
        "C": [(0.02 if i % 2 else -0.02) for i in range(40)],           # mean 0
    }
    out = sweep_validation_report(per_cfg)
    assert out["best_config"] == "A"
    assert out["pbo"] == 0.0
    assert out["deflated_sharpe"] > 0.9
    assert out["verdict"] == "robust"


def test_sweep_likely_overfit_for_spike_matrix():
    # config n profits only in period n -> whatever wins in-sample is flat out-of-sample
    per_cfg = {f"c{n}": [1.0 if t == n else 0.0 for t in range(8)] for n in range(8)}
    out = sweep_validation_report(per_cfg, n_splits=8)
    assert out["pbo"] == 1.0
    assert out["verdict"] == "likely_overfit"


def test_report_from_results_wraps_end_to_end():
    results = {
        "A": {"trades": [{"ts": "2026-01-0%d" % d, "pnl": 800.0} for d in range(1, 9)]},
        "B": {"trades": [{"ts": "2026-01-0%d" % d, "pnl": -100.0} for d in range(1, 9)]},
    }
    out = report_from_results(results, 100_000, n_splits=8)
    assert out["configs"] == 2 and "verdict" in out and "deflated_sharpe" in out


# ----------------------------------------------------- PSR in compute_metrics
def test_compute_metrics_includes_psr():
    trades = [{"ts": f"t{i}", "pnl": 100.0 if i % 3 else -80.0,
               "r_multiple": 1.0 if i % 3 else -0.8} for i in range(30)]
    m = compute_metrics(trades, 100_000)
    assert "psr" in m and 0.0 <= m["psr"] <= 1.0


def test_compute_metrics_empty_has_psr_zero():
    assert compute_metrics([], 100_000)["psr"] == 0.0
