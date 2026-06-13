import numpy as np

from ml import pipeline as P


def test_end_to_end_cpcv(close, feature_matrix):
    events = P.make_events(close, vol_span=20, vertical_bars=10)
    assert len(events) > 100

    barrier = P.label_events(close, events, pt_sl=(1.5, 1.5))
    X, y, t1 = P.build_dataset(feature_matrix, barrier)

    assert len(X) > 50
    assert list(X.index) == sorted(X.index)            # chronological
    assert set(np.unique(y)).issubset({0, 1})

    res = P.evaluate_cpcv(X, y, t1, n_groups=6, n_test_groups=2, embargo_pct=0.01)
    assert res["n_paths"] == 5
    assert res["n_splits_used"] >= 1
    assert 0.0 <= res["mean"] <= 1.0
    assert res["scores"].size == res["n_splits_used"]
