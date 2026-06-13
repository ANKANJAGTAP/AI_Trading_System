"""
Leakage-aware cross-validation (AFML ch. 7).

Financial labels overlap in time (a label at t0 depends on prices up to its
barrier t1), so naive K-fold leaks future information into training. These
splitters PURGE training observations whose label window overlaps the test
window, and EMBARGO a buffer after each test block.

  * PurgedKFold            — sequential folds, purged + embargoed.
  * combinatorial_purged_cv — many train/test group combinations, giving a
    DISTRIBUTION of out-of-sample performance (CPCV) instead of one path.
"""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd


def _embargo_bars(n: int, pct: float) -> int:
    return int(n * pct)


class PurgedKFold:
    """K-fold where train obs overlapping the test window are purged."""

    def __init__(self, n_splits: int, t1: pd.Series, embargo_pct: float = 0.0):
        self.n_splits = n_splits
        self.t1 = t1                      # index = sample start, value = label end
        self.embargo_pct = embargo_pct

    def split(self, X: pd.DataFrame):
        if len(X) != len(self.t1):
            raise ValueError("X and t1 must align")
        idx = np.arange(len(X))
        emb = _embargo_bars(len(X), self.embargo_pct)
        starts = self.t1.index
        for grp in np.array_split(idx, self.n_splits):
            test_idx = grp
            t_lo = starts[test_idx[0]]
            t_hi = self.t1.iloc[test_idx].max()
            # left train: labels that end before the test window opens
            left = idx[(self.t1 <= t_lo).to_numpy()]
            # right train: samples that start after the test window (+ embargo)
            hi_loc = min(int(starts.searchsorted(t_hi)) + emb, len(X))
            right = idx[hi_loc:]
            train_idx = np.setdiff1d(np.concatenate([left, right]), test_idx)
            yield train_idx, test_idx


def num_cpcv_paths(n_groups: int, n_test_groups: int) -> int:
    """Number of backtest paths CPCV produces (AFML eq.)."""
    n_splits = math.comb(n_groups, n_test_groups)
    return n_splits * n_test_groups // n_groups


def combinatorial_purged_cv(X: pd.DataFrame, t1: pd.Series,
                            n_groups: int = 6, n_test_groups: int = 2,
                            embargo_pct: float = 0.0):
    """Yield (train_idx, test_idx) for every choice of `n_test_groups` test
    groups out of `n_groups`, purging train against each test block."""
    if len(X) != len(t1):
        raise ValueError("X and t1 must align")
    idx = np.arange(len(X))
    groups = [g for g in np.array_split(idx, n_groups)]
    starts = t1.index
    emb = _embargo_bars(len(X), embargo_pct)

    for combo in itertools.combinations(range(n_groups), n_test_groups):
        test_idx = np.sort(np.concatenate([groups[g] for g in combo]))
        train_idx = np.setdiff1d(idx, test_idx)
        # purge against each (contiguous) test group block
        for g in combo:
            block = groups[g]
            lo = starts[block[0]]
            hi = t1.iloc[block].max()
            hi_loc = min(int(starts.searchsorted(hi)) + emb, len(X))
            keep = []
            for j in train_idx:
                ends_before = t1.iloc[j] < lo
                starts_after = j >= hi_loc
                if ends_before or starts_after:
                    keep.append(j)
            train_idx = np.array(keep, dtype=int)
        yield train_idx, test_idx
