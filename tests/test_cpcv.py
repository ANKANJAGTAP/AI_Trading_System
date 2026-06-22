"""§10 Phase 2 — Combinatorial Purged Cross-Validation."""
from math import comb

from backtest.cpcv import cpcv_splits, make_groups, n_backtest_paths


def test_make_groups_partitions_evenly():
    assert make_groups(10, 5) == [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]]
    assert sum(len(g) for g in make_groups(13, 4)) == 13     # remainder absorbed


def test_n_backtest_paths():
    assert n_backtest_paths(6, 2) == comb(6, 2) * 2 // 6      # 5
    assert n_backtest_paths(1, 1) == 0                        # degenerate


def test_cpcv_splits_count_and_disjoint():
    splits = cpcv_splits(12, n_groups=6, k_test=2)
    assert len(splits) == comb(6, 2)                          # 15 combinations
    for s in splits:
        assert set(s["test"]).isdisjoint(s["train"])         # never train on test
        assert len(s["test"]) == 4                            # 2 groups x 2 obs


def test_embargo_drops_following_indices():
    no_emb = cpcv_splits(12, 6, 2, embargo=0)[0]
    emb = cpcv_splits(12, 6, 2, embargo=1)[0]
    assert len(emb["train"]) <= len(no_emb["train"])         # embargo removes some train


def test_degenerate_params_return_empty():
    assert cpcv_splits(5, n_groups=6, k_test=2) == []        # fewer obs than groups
    assert cpcv_splits(12, n_groups=4, k_test=4) == []       # k_test not < n_groups
