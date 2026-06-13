import math

import numpy as np
import pandas as pd

from ml.cv import PurgedKFold, combinatorial_purged_cv, num_cpcv_paths


def _xy(n=120, span=3):
    idx = pd.bdate_range("2021-01-01", periods=n)
    X = pd.DataFrame({"f": np.arange(n)}, index=idx)
    ends = [idx[min(i + span, n - 1)] for i in range(n)]
    t1 = pd.Series(ends, index=idx)
    return X, t1


def test_purged_kfold_no_overlap_and_covers_all():
    X, t1 = _xy()
    pk = PurgedKFold(n_splits=5, t1=t1, embargo_pct=0.0)
    seen = []
    for train, test in pk.split(X):
        assert len(set(train) & set(test)) == 0
        t_lo = t1.index[test[0]]
        t_hi = t1.iloc[test].max()
        for j in train:
            tr_start, tr_end = t1.index[j], t1.iloc[j]
            assert (tr_end <= t_lo) or (tr_start >= t_hi), "leakage in PurgedKFold"
        seen.append(test)
    assert sorted(np.concatenate(seen)) == list(range(len(X)))


def test_num_cpcv_paths():
    assert num_cpcv_paths(6, 2) == 5
    assert num_cpcv_paths(10, 2) == 9


def test_cpcv_count_and_disjoint():
    X, t1 = _xy()
    splits = list(combinatorial_purged_cv(X, t1, n_groups=6, n_test_groups=2,
                                          embargo_pct=0.01))
    assert len(splits) == math.comb(6, 2) == 15
    for train, test in splits:
        assert len(set(train) & set(test)) == 0
        # no surviving train label-window overlaps ANY test sample's window
        test_starts = t1.index[test].to_numpy()
        test_ends = t1.iloc[test].to_numpy()
        for j in train:
            s, e = t1.index[j], t1.iloc[j]
            overlap = (np.datetime64(s) <= test_ends) & (np.datetime64(e) >= test_starts)
            assert not overlap.any(), "leakage: train window overlaps a test window"

