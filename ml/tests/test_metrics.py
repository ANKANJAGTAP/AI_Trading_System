import numpy as np
import pandas as pd

from ml import metrics as M


def test_sharpe():
    assert M.sharpe_ratio(np.full(100, 0.001)) > 0
    assert M.sharpe_ratio(np.zeros(100)) == 0.0


def test_psr_monotonic_and_bounded():
    a = M.probabilistic_sharpe_ratio(0.05, 200)
    b = M.probabilistic_sharpe_ratio(0.20, 200)
    assert 0 <= a <= 1 and 0 <= b <= 1 and b > a


def test_expected_max_sharpe_increases_with_trials():
    assert M.expected_max_sharpe(1, 0.01) == 0.0
    assert M.expected_max_sharpe(50, 0.01) > M.expected_max_sharpe(5, 0.01)


def test_deflated_not_greater_than_undeflated():
    sr, n = 0.2, 250
    ests = [0.20, 0.15, 0.10, 0.25, 0.05, 0.18, 0.22]
    dsr = M.deflated_sharpe_ratio(sr, n, ests)
    psr0 = M.probabilistic_sharpe_ratio(sr, n, sr_benchmark=0.0)
    assert 0 <= dsr <= 1
    assert dsr <= psr0 + 1e-9          # deflation can only lower the bar's pass-prob


def test_pbo_low_for_dominant_config():
    rng = np.random.default_rng(0)
    perf = rng.normal(0, 0.01, (240, 3))
    perf[:, 2] += 0.02                 # config 2 genuinely dominates
    assert 0 <= M.pbo_cscv(pd.DataFrame(perf), n_splits=8) < 0.35


def test_pbo_in_range_for_noise():
    rng = np.random.default_rng(1)
    perf = pd.DataFrame(rng.normal(0, 0.01, (200, 5)))
    assert 0 <= M.pbo_cscv(perf, n_splits=8) <= 1


def test_drawdown_and_profit_factor():
    r = np.array([0.1, -0.2, 0.05, -0.1, 0.2])
    assert M.max_drawdown(r) < 0
    assert M.profit_factor(r) > 0
