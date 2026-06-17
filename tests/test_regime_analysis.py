"""#26 — regime-bucketed performance + parameter-decay kill criteria."""
from backtest.regime_analysis import bucket_by_regime, parameter_decay


def test_bucket_by_regime_separates_edge():
    trades = [
        {"r_multiple": 2.0, "features": {"regime": "trending_up"}},
        {"r_multiple": 1.0, "features": {"regime": "trending_up"}},
        {"r_multiple": -1.0, "features": {"regime": "choppy"}},
        {"r_multiple": -1.0, "features": {"regime": "choppy"}},
        {"r_multiple": None, "features": {"regime": "choppy"}},   # skipped (no R)
    ]
    out = bucket_by_regime(trades)
    assert out["trending_up"]["trades"] == 2 and out["trending_up"]["expectancy_R"] == 1.5
    assert out["trending_up"]["win_rate"] == 100.0
    assert out["choppy"]["trades"] == 2 and out["choppy"]["expectancy_R"] == -1.0


def test_bucket_reads_top_level_or_features_regime():
    trades = [{"r_multiple": 1.0, "regime": "trend"}, {"r_multiple": -0.5, "regime": "trend"}]
    out = bucket_by_regime(trades)
    assert out["trend"]["trades"] == 2 and out["trend"]["total_R"] == 0.5


def test_parameter_decay_insufficient_history():
    assert parameter_decay([0.2, 0.1], recent=3)["kill"] is False


def test_parameter_decay_stable_edge():
    out = parameter_decay([0.3, 0.35, 0.3, 0.32, 0.31], recent=2)
    assert out["kill"] is False and out["decaying"] in (False, True)


def test_parameter_decay_kills_on_negative_recent():
    out = parameter_decay([0.4, 0.3, 0.35, -0.1, -0.2], recent=2)
    assert out["kill"] is True and out["recent"] < 0


def test_parameter_decay_kills_on_large_drop_from_positive_baseline():
    # baseline ~0.4, recent ~0.1 -> >50% drop -> kill
    out = parameter_decay([0.4, 0.42, 0.40, 0.10, 0.08], recent=2, drop_frac=0.5)
    assert out["kill"] is True and out["decaying"] is True
