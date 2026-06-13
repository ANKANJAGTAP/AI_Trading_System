import numpy as np

from ml.models import LogisticMetaModel, size_multiplier


def test_logistic_learns_separable():
    rng = np.random.default_rng(0)
    X = rng.normal(0, 1, (400, 2))
    y = (X[:, 0] + 0.3 * rng.normal(0, 1, 400) > 0).astype(int)
    m = LogisticMetaModel(n_iter=2000).fit(X, y)
    acc = (m.predict(X) == y).mean()
    assert acc > 0.85
    p = m.predict_proba(X)
    assert ((p >= 0) & (p <= 1)).all()


def test_sample_weight_runs():
    rng = np.random.default_rng(1)
    X = rng.normal(0, 1, (200, 3))
    y = (X[:, 0] > 0).astype(int)
    w = rng.uniform(0.5, 1.5, 200)
    m = LogisticMetaModel(class_weight=True).fit(X, y, sample_weight=w)
    assert m.predict_proba(X).shape == (200,)


def test_size_multiplier_rule():
    assert size_multiplier(0.30) == 0.0          # veto
    assert size_multiplier(0.70) == 1.0          # full size
    assert 0.0 < size_multiplier(0.50) < 1.0     # ramp
    assert size_multiplier(0.45) < size_multiplier(0.55)   # monotone
    arr = size_multiplier(np.array([0.30, 0.50, 0.70]))
    assert arr.shape == (3,) and arr[0] == 0.0 and arr[2] == 1.0


def test_size_multiplier_never_exceeds_one():
    for p in np.linspace(0, 1, 50):
        assert size_multiplier(p) <= 1.0
