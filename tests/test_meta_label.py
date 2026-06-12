"""Phase 4: meta-labeler (logistic regression) + dataset feature assembly."""
import numpy as np

from research.dataset import feature_names, to_matrix
from research.meta_label import MetaLabeler, evaluate, feature_importance, predict_proba, train


def test_logreg_learns_separable_pattern():
    # label 1 when feature0 high, 0 when low -> learnable
    rng = np.random.default_rng(0)
    pos = rng.normal(2.0, 0.3, size=(60, 2))
    neg = rng.normal(-2.0, 0.3, size=(60, 2))
    X = np.vstack([pos, neg]).tolist()
    y = [1] * 60 + [0] * 60
    params = train(X, y)
    m = evaluate(params, X, y)
    assert m["accuracy"] > 0.9
    # high-feature point -> high win prob, low-feature -> low
    assert predict_proba(params, [2.0, 2.0]) > 0.7
    assert predict_proba(params, [-2.0, -2.0]) < 0.3


def test_predict_proba_bounded():
    params = train([[1, 1], [-1, -1], [2, 2], [-2, -2]], [1, 0, 1, 0])
    for x in ([5, 5], [-5, -5], [0, 0]):
        p = predict_proba(params, x)
        assert 0.0 <= p <= 1.0


def test_feature_names_and_matrix():
    samples = [
        {"features": {"confidence": 0.6, "regime_up": 1.0, "rvol": 0.5}, "label": 1},
        {"features": {"confidence": 0.4, "regime_up": 0.0}, "label": 0},
    ]
    feats = feature_names(samples)
    assert "confidence" in feats and "regime_up" in feats and "rvol" in feats
    X, y = to_matrix(samples, feats)
    assert len(X) == 2 and len(X[0]) == len(feats)
    assert y == [1, 0]
    # missing feature defaults to 0.0
    assert X[1][feats.index("rvol")] == 0.0


def test_meta_labeler_filter_semantics():
    """Dead-band filter: low win-prob -> hard veto (0.0), high -> untouched (1.0),
    middle -> mild shrink. Never inflates confidence."""
    params = train([[1, 1], [-1, -1], [2, 2], [-2, -2]], [1, 0, 1, 0])
    params["deploy"] = {"veto_below": 0.40, "neutral_above": 0.55, "soft_floor": 0.6}
    ml = MetaLabeler(["confidence", "rvol"], params)
    high = ml.assess({"confidence": 3.0, "rvol": 3.0})     # clearly winning pattern
    low = ml.assess({"confidence": -3.0, "rvol": -3.0})    # clearly losing pattern
    assert high == 1.0      # no inflation, no needless shrink
    assert low == 0.0       # hard veto
    # dead band: a borderline p lands between soft_floor and 1.0
    p_mid = ml.win_probability({"confidence": 0.05, "rvol": 0.0})
    adj_mid = ml.assess({"confidence": 0.05, "rvol": 0.0})
    if 0.40 <= p_mid < 0.55:
        assert 0.6 <= adj_mid < 1.0
    assert 0.0 <= adj_mid <= 1.0


def test_feature_importance_sorted_by_magnitude():
    params = {"w": [0.1, -0.9, 0.4], "b": 0.0, "mu": [0, 0, 0], "sd": [1, 1, 1]}
    imp = feature_importance(params, ["a", "b", "c"])
    assert imp[0]["feature"] == "b"   # largest |weight| first
