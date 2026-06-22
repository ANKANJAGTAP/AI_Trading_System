"""Combinatorial Purged Cross-Validation (§10 Phase 2) — pure, no I/O.

López de Prado's CPCV: split the series into G groups and use every C(G, k) choice of
k groups as the test set, purging an embargo of observations right after each test
block from train so no look-ahead leaks. Unlike a single walk-forward, CPCV yields
MANY back-test paths (C(G,k)·k/G of them), which is what makes PBO / Deflated-Sharpe
estimates statistically meaningful instead of one lucky split.
"""
from __future__ import annotations

import itertools
from math import comb


def make_groups(n_obs: int, n_groups: int) -> list[list[int]]:
    """Partition range(n_obs) into n_groups contiguous, near-equal index groups."""
    base, rem = divmod(n_obs, n_groups)
    groups, start = [], 0
    for i in range(n_groups):
        size = base + (1 if i < rem else 0)
        groups.append(list(range(start, start + size)))
        start += size
    return groups


def n_backtest_paths(n_groups: int, k_test: int) -> int:
    """Number of OOS back-test paths CPCV produces: C(G,k)·k/G."""
    if n_groups < 2 or not (1 <= k_test < n_groups):
        return 0
    return comb(n_groups, k_test) * k_test // n_groups


def cpcv_splits(n_obs: int, n_groups: int = 6, k_test: int = 2, embargo: int = 0) -> list[dict]:
    """All combinatorial train/test splits. test = k_test groups; train = the rest minus
    an `embargo` of indices immediately following each test block (purge the leak).
    Returns [{"test": [...], "train": [...]}]; empty on degenerate params."""
    if n_groups < 2 or not (1 <= k_test < n_groups) or n_obs < n_groups:
        return []
    groups = make_groups(n_obs, n_groups)
    splits = []
    for combo in itertools.combinations(range(n_groups), k_test):
        test_set = {i for g in combo for i in groups[g]}
        embargoed: set[int] = set()
        if embargo > 0:
            for g in combo:
                last = groups[g][-1]
                embargoed.update(range(last + 1, min(n_obs, last + 1 + embargo)))
        train_idx = [i for i in range(n_obs) if i not in test_set and i not in embargoed]
        splits.append({"test": sorted(test_set), "train": train_idx})
    return splits
