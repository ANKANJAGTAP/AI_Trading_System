"""Backtest-validity statistics (§4/§10) — pure, stdlib only.

The question every backtest must answer is "is this edge real, or did I curve-fit
it?" Three tools, all from Bailey & López de Prado:

  * Probabilistic Sharpe Ratio (PSR) — the probability the true Sharpe exceeds a
    benchmark, correcting the naive Sharpe for sample length, skew, and fat tails.
  * Deflated Sharpe Ratio (DSR) — PSR against a benchmark that accounts for the
    NUMBER OF TRIALS you ran. Try enough variants and one will look great by luck;
    the DSR deflates the observed Sharpe by the expected maximum of that many
    independent zero-skill trials.
  * Probability of Backtest Overfitting (PBO) via Combinatorially Symmetric Cross-
    Validation (CSCV) — across all train/test splits, how often the in-sample-best
    configuration lands in the OOS bottom half. High PBO = your selection process
    overfits.

No numpy/scipy: `statistics.NormalDist` gives the normal CDF and its inverse.
"""
from __future__ import annotations

import math
import statistics as st
from itertools import combinations
from statistics import NormalDist

_N = NormalDist()
_GAMMA = 0.5772156649015329          # Euler–Mascheroni constant


# --------------------------------------------------------------- moments
def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _pstdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def sharpe_ratio(returns: list[float]) -> float:
    """Per-observation Sharpe (mean / population-stdev). NOT annualized — keep the
    DSR/PSR machinery in the same per-observation units throughout."""
    s = _pstdev(returns)
    return _mean(returns) / s if s > 0 else 0.0


def skewness(returns: list[float]) -> float:
    n = len(returns)
    if n < 3:
        return 0.0
    m, s = _mean(returns), _pstdev(returns)
    return sum(((x - m) / s) ** 3 for x in returns) / n if s > 0 else 0.0


def kurtosis(returns: list[float]) -> float:
    """Non-excess kurtosis (normal distribution -> 3.0)."""
    n = len(returns)
    if n < 4:
        return 3.0
    m, s = _mean(returns), _pstdev(returns)
    return sum(((x - m) / s) ** 4 for x in returns) / n if s > 0 else 3.0


# --------------------------------------------------------------- PSR / DSR
def _psr(sr: float, t_obs: int, skew: float, kurt: float, sr_benchmark: float) -> float:
    """Probabilistic Sharpe Ratio core: Φ[ (SR - SR*)·√(T-1) /
    √(1 - skew·SR + (kurt-1)/4·SR²) ]."""
    if t_obs < 2:
        return 0.0
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr))
    z = (sr - sr_benchmark) * math.sqrt(t_obs - 1) / denom
    return _N.cdf(z)


def probabilistic_sharpe_ratio(returns: list[float], sr_benchmark: float = 0.0) -> float:
    """Probability the true Sharpe exceeds `sr_benchmark`, given the sample's length,
    skew, and kurtosis. 0.5 means the observed Sharpe equals the benchmark."""
    return _psr(sharpe_ratio(returns), len(returns), skewness(returns),
               kurtosis(returns), sr_benchmark)


def expected_max_sharpe(n_trials: int, sr_std: float) -> float:
    """Expected maximum of `n_trials` independent zero-mean Sharpe ratios with
    cross-trial std `sr_std` (Bailey & López de Prado). The benchmark a real edge
    must beat after multiple testing."""
    if n_trials < 2 or sr_std <= 0:
        return 0.0
    a = _N.inv_cdf(1.0 - 1.0 / n_trials)
    b = _N.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return sr_std * ((1.0 - _GAMMA) * a + _GAMMA * b)


def deflated_sharpe_ratio(returns: list[float], trial_sharpes: list[float]) -> float:
    """PSR against the expected-max-Sharpe benchmark for the number of trials run.
    `trial_sharpes` = the per-observation Sharpe of every configuration you tried
    (its length is the trial count; its spread sets the benchmark). DSR in [0,1];
    near 1 = robust after deflation, near 0 = likely a multiple-testing artifact."""
    sr = sharpe_ratio(returns)
    n = len(trial_sharpes) if trial_sharpes else 1
    sr_std = _pstdev(trial_sharpes) if n > 1 else 0.0
    sr0 = expected_max_sharpe(n, sr_std)
    return _psr(sr, len(returns), skewness(returns), kurtosis(returns), sr0)


# --------------------------------------------------------------- PBO (CSCV)
def _split_indices(t_rows: int, n_splits: int) -> list[list[int]]:
    """Partition row indices 0..t_rows-1 into n_splits contiguous, near-equal chunks."""
    base, rem = divmod(t_rows, n_splits)
    out, start = [], 0
    for i in range(n_splits):
        size = base + (1 if i < rem else 0)
        out.append(list(range(start, start + size)))
        start += size
    return out


def pbo_cscv(matrix: list[list[float]], n_splits: int = 10, metric=None) -> dict:
    """Probability of Backtest Overfitting via CSCV.

    `matrix` is T periods (rows) × N configurations (cols); cell = that config's
    per-period performance (e.g. return). For every way to split the periods into
    equal IS/OOS halves, pick the IS-best config and measure its OOS rank; PBO is
    the fraction of splits where that pick lands in the OOS bottom half. `metric`
    maps a list of a config's period values to a score (default: Sharpe).
    """
    metric = metric or sharpe_ratio
    t_rows = len(matrix)
    n_cfg = len(matrix[0]) if matrix else 0
    if t_rows < 2 or n_cfg < 2:
        return {"pbo": 0.0, "n_combinations": 0, "n_configs": n_cfg, "n_splits": 0}

    s = n_splits + (n_splits % 2)            # force even
    s = min(s, t_rows - (t_rows % 2) or 2)   # no more splits than rows (keep even)
    if s < 2:
        return {"pbo": 0.0, "n_combinations": 0, "n_configs": n_cfg, "n_splits": 0}

    chunks = _split_indices(t_rows, s)

    def perf(rows: list[int], col: int) -> float:
        return metric([matrix[r][col] for r in rows])

    overfit, logits = 0, []
    for is_sel in combinations(range(s), s // 2):
        is_set = set(is_sel)
        is_rows = [r for c in is_sel for r in chunks[c]]
        oos_rows = [r for c in range(s) if c not in is_set for r in chunks[c]]
        is_perf = [perf(is_rows, n) for n in range(n_cfg)]
        oos_perf = [perf(oos_rows, n) for n in range(n_cfg)]
        n_star = max(range(n_cfg), key=lambda n: is_perf[n])
        rank = sum(1 for n in range(n_cfg) if oos_perf[n] <= oos_perf[n_star])  # 1..N
        omega = min(max(rank / (n_cfg + 1), 1e-6), 1 - 1e-6)
        lam = math.log(omega / (1 - omega))
        logits.append(lam)
        if lam <= 0:                          # IS-best at/below OOS median -> overfit
            overfit += 1

    combos = len(logits)
    return {
        "pbo": overfit / combos if combos else 0.0,
        "n_combinations": combos,
        "n_configs": n_cfg,
        "n_splits": s,
        "median_logit": round(st.median(logits), 4) if logits else 0.0,
    }
