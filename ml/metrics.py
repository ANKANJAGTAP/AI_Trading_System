"""
Performance & overfitting metrics — the gate that decides if an edge is real.

  * sharpe_ratio
  * probabilistic_sharpe_ratio (PSR)   — is SR > benchmark given skew/kurtosis & n?
  * deflated_sharpe_ratio (DSR)        — PSR adjusted for the number of trials run
  * pbo_cscv                           — Probability of Backtest Overfitting (CSCV)
plus drawdown / profit-factor / expectancy helpers.

Uses statistics.NormalDist (stdlib) for the normal CDF/quantile — no SciPy.
"""
from __future__ import annotations

import itertools
import math
from statistics import NormalDist

import numpy as np
import pandas as pd

_N = NormalDist()
_EULER = 0.5772156649015329


def sharpe_ratio(returns, periods: int = 252) -> float:
    r = np.asarray(returns, dtype=float)
    sd = r.std(ddof=1)
    if sd == 0 or len(r) < 2:
        return 0.0
    return float(r.mean() / sd * math.sqrt(periods))


def probabilistic_sharpe_ratio(sr, n, skew=0.0, kurt=3.0, sr_benchmark=0.0) -> float:
    """P(true SR > benchmark). sr and benchmark are per-observation (non-annualised
    if n is the number of observations); skew/kurt are of the return distribution."""
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4.0 * sr ** 2, 1e-12))
    return float(_N.cdf((sr - sr_benchmark) * math.sqrt(n - 1) / denom))


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """Expected maximum Sharpe across `n_trials` independent trials (AFML)."""
    if n_trials < 2 or var_sr <= 0:
        return 0.0
    z1 = _N.inv_cdf(1 - 1.0 / n_trials)
    z2 = _N.inv_cdf(1 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_sr) * ((1 - _EULER) * z1 + _EULER * z2)


def deflated_sharpe_ratio(sr, n, sr_estimates, skew=0.0, kurt=3.0) -> float:
    """DSR: PSR with the benchmark set to the expected max Sharpe from the
    multiple trials you actually ran. `sr_estimates` = the SR of every trial."""
    est = np.asarray(sr_estimates, dtype=float)
    var_sr = est.var(ddof=1) if len(est) > 1 else 0.0
    sr_star = expected_max_sharpe(len(est), var_sr)
    return probabilistic_sharpe_ratio(sr, n, skew, kurt, sr_star)


def pbo_cscv(perf: pd.DataFrame, n_splits: int = 10) -> float:
    """Probability of Backtest Overfitting via combinatorially-symmetric CV.

    `perf`: DataFrame (T periods x N configurations) of per-period returns.
    Returns PBO in [0,1]: the probability the in-sample-best config ranks below
    the OOS median. High PBO (->1) => your selection is likely overfit.
    """
    T, ncfg = perf.shape
    if ncfg < 2:
        return float("nan")
    groups = [g for g in np.array_split(np.arange(T), n_splits)]
    logits = []
    for combo in itertools.combinations(range(n_splits), n_splits // 2):
        is_rows = np.concatenate([groups[g] for g in combo])
        oos_rows = np.concatenate([groups[g] for g in range(n_splits) if g not in combo])
        is_perf = perf.iloc[is_rows].mean()
        oos_perf = perf.iloc[oos_rows].mean()
        best = is_perf.idxmax()
        rank = oos_perf.rank().loc[best]          # 1..ncfg (1 worst)
        w = rank / (ncfg + 1)
        w = min(max(w, 1e-6), 1 - 1e-6)
        logits.append(math.log(w / (1 - w)))
    logits = np.array(logits)
    return float((logits <= 0).mean())


# ---- plain performance stats ------------------------------------------- #
def max_drawdown(returns) -> float:
    r = np.asarray(returns, dtype=float)
    equity = np.cumprod(1 + r)
    peak = np.maximum.accumulate(equity)
    return float((equity / peak - 1).min()) if len(r) else 0.0


def profit_factor(returns) -> float:
    r = np.asarray(returns, dtype=float)
    gains = r[r > 0].sum()
    losses = -r[r < 0].sum()
    return float(gains / losses) if losses > 0 else float("inf")


def expectancy(returns) -> float:
    r = np.asarray(returns, dtype=float)
    return float(r.mean()) if len(r) else 0.0
