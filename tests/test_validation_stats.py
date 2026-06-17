"""Tests for backtest-validity stats: PSR, Deflated Sharpe, and PBO (CSCV).

Anchored on known limiting behaviour (PSR=0.5 at the benchmark, monotonicity,
deterministic PBO=0 for a dominant config and PBO=1 for a built overfit matrix)
rather than fragile magic numbers.
"""
from backtest.validation import (deflated_sharpe_ratio, expected_max_sharpe,
                                  kurtosis, pbo_cscv, probabilistic_sharpe_ratio,
                                  sharpe_ratio, skewness)

_ALT = [0.1 + (1.0 if i % 2 == 0 else -1.0) for i in range(500)]  # mean .1, sd ~1


# ----------------------------------------------------- moments / sharpe
def test_sharpe_and_moments_basic():
    assert round(sharpe_ratio(_ALT), 3) == round(0.1 / 1.0, 3)
    assert abs(skewness(_ALT)) < 1e-6                 # symmetric
    assert kurtosis([1, 1, 1, 1]) == 3.0              # degenerate -> normal default
    assert sharpe_ratio([]) == 0.0 and sharpe_ratio([5, 5, 5]) == 0.0


# ----------------------------------------------------- PSR
def test_psr_half_at_benchmark():
    sr = sharpe_ratio(_ALT)
    assert abs(probabilistic_sharpe_ratio(_ALT, sr_benchmark=sr) - 0.5) < 1e-6


def test_psr_monotonic_in_benchmark_and_bounds():
    low = probabilistic_sharpe_ratio(_ALT, sr_benchmark=0.0)
    high = probabilistic_sharpe_ratio(_ALT, sr_benchmark=0.2)
    assert low > high                                  # harder benchmark -> lower prob
    assert 0.0 <= high < low <= 1.0
    assert low > 0.9                                   # sr .1 over 500 obs vs 0 is strong


# ----------------------------------------------------- expected max sharpe
def test_expected_max_sharpe_grows_with_trials():
    assert expected_max_sharpe(1, 1.0) == 0.0          # a single trial has no selection bias
    assert expected_max_sharpe(2, 0.0) == 0.0          # no cross-trial variance -> 0
    e10, e100, e1000 = (expected_max_sharpe(n, 1.0) for n in (10, 100, 1000))
    assert 0 < e10 < e100 < e1000                      # more trials -> higher bar


# ----------------------------------------------------- Deflated Sharpe
def test_dsr_in_unit_interval_and_penalizes_trials():
    sr = sharpe_ratio(_ALT)
    dsr_single = deflated_sharpe_ratio(_ALT, trial_sharpes=[sr])          # 1 trial
    spread = [sr + 0.15 * ((i % 7) - 3) / 3 for i in range(60)]          # 60 trials, real spread
    dsr_many = deflated_sharpe_ratio(_ALT, trial_sharpes=spread)
    assert 0.0 <= dsr_many <= dsr_single <= 1.0
    assert dsr_single > 0.9            # essentially one trial -> survives
    assert dsr_many < dsr_single       # many diverse trials -> deflated


# ----------------------------------------------------- PBO (CSCV)
def test_pbo_zero_for_dominant_config():
    # config 0 is best in every single period -> IS-best is always OOS-best -> PBO 0
    matrix = [[10.0, 1.0, 2.0, 3.0] for _ in range(8)]
    # make non-dominant cols vary a little so metric is well-defined, col 0 still tops
    for t in range(8):
        matrix[t] = [10.0 + t * 0.01, 1.0 + (t % 3), 2.0 + (t % 2), 3.0 - (t % 2)]
    out = pbo_cscv(matrix, n_splits=8, metric=lambda xs: sum(xs) / len(xs))
    assert out["pbo"] == 0.0
    assert out["n_combinations"] == 70                 # C(8,4)


def test_pbo_one_for_constructed_overfit_matrix():
    # config n spikes only in period n: whatever wins in-sample is flat out-of-sample
    n = 8
    matrix = [[1.0 if t == c else 0.0 for c in range(n)] for t in range(n)]
    out = pbo_cscv(matrix, n_splits=8, metric=lambda xs: sum(xs) / len(xs))
    assert out["pbo"] == 1.0


def test_pbo_bounds_and_shape():
    matrix = [[((i * 7 + j * 13) % 11) / 11.0 for j in range(5)] for i in range(12)]
    out = pbo_cscv(matrix, n_splits=10)
    assert 0.0 <= out["pbo"] <= 1.0
    assert out["n_configs"] == 5 and out["n_splits"] == 10


def test_pbo_handles_degenerate_input():
    assert pbo_cscv([], n_splits=8)["pbo"] == 0.0
    assert pbo_cscv([[1.0]], n_splits=8)["pbo"] == 0.0          # one config
    assert pbo_cscv([[1.0, 2.0]], n_splits=8)["pbo"] == 0.0     # one row
