"""§10 Phase 3 — bootstrap / Monte-Carlo on trade returns."""
from backtest.monte_carlo import bootstrap_paths, risk_of_ruin, summary


def test_deterministic_with_seed():
    a = bootstrap_paths([1.0, -1.0, 2.0], horizon=10, n_paths=50, seed=42)
    b = bootstrap_paths([1.0, -1.0, 2.0], horizon=10, n_paths=50, seed=42)
    assert a == b and len(a) == 50


def test_all_positive_no_drawdown_no_ruin():
    s = summary([1.0, 2.0], horizon=10, n_paths=200, seed=1)
    assert s["terminal_p05"] > 0 and s["median_drawdown"] == 0.0
    assert risk_of_ruin([1.0, 2.0], horizon=10, ruin_threshold=5, n_paths=200) == 0.0


def test_all_negative_high_ruin():
    ror = risk_of_ruin([-1.0, -2.0], horizon=20, ruin_threshold=5, n_paths=200, seed=3)
    assert ror > 0.9


def test_summary_percentiles_ordered():
    s = summary([1.0, -1.0, 2.0, -2.0], horizon=30, n_paths=500, seed=7)
    assert s["terminal_p05"] <= s["terminal_p50"] <= s["terminal_p95"]
    assert s["paths"] == 500


def test_empty_inputs_safe():
    assert summary([], horizon=10) == {"paths": 0}
    assert risk_of_ruin([], horizon=10, ruin_threshold=5) == 0.0
    assert bootstrap_paths([1.0], horizon=0) == []
