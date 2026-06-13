import numpy as np
import pandas as pd

from ml import sample_weights as sw


def _setup():
    idx = pd.bdate_range("2022-01-03", periods=12)
    # three events: two overlap early, one separate later
    t1 = pd.Series(
        [idx[4], idx[5], idx[10]],
        index=[idx[0], idx[1], idx[7]],
    )
    return idx, t1


def test_concurrency_counts():
    idx, t1 = _setup()
    co = sw.num_concurrent_events(idx, t1)
    assert co.loc[idx[2]] == 2     # events 0 and 1 both open
    assert co.loc[idx[8]] == 1     # only event 2 open
    assert co.loc[idx[6]] == 0     # gap between events


def test_average_uniqueness_bounds():
    idx, t1 = _setup()
    co = sw.num_concurrent_events(idx, t1)
    au = sw.average_uniqueness(t1, co)
    assert ((au > 0) & (au <= 1)).all()
    # the isolated event (no overlap) is fully unique
    assert abs(au.loc[idx[7]] - 1.0) < 1e-9


def test_time_decay_no_decay_is_flat():
    idx, t1 = _setup()
    co = sw.num_concurrent_events(idx, t1)
    au = sw.average_uniqueness(t1, co)
    w = sw.time_decay_weights(au, last_weight=1.0)
    assert np.allclose(w.to_numpy(), 1.0)


def test_time_decay_monotone():
    idx, t1 = _setup()
    co = sw.num_concurrent_events(idx, t1)
    au = sw.average_uniqueness(t1, co)
    w = sw.time_decay_weights(au, last_weight=0.0)   # oldest decays toward 0
    assert w.iloc[0] < w.iloc[-1]


def test_combined_weights_normalised():
    idx, t1 = _setup()
    w = sw.combined_weights(t1, idx)
    assert abs(w.mean() - 1.0) < 1e-9
