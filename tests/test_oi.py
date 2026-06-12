"""OI buildup classification (data/oi.py) — the price x OI truth table."""
from data.oi import buildup_bias, classify_buildup


def test_buildup_truth_table():
    assert classify_buildup(+1, +1) == "long_buildup_bullish"
    assert classify_buildup(-1, +1) == "short_buildup_bearish"
    assert classify_buildup(+1, -1) == "short_covering"
    assert classify_buildup(-1, -1) == "long_unwinding"


def test_buildup_neutral_on_flat():
    assert classify_buildup(0, 5) == "neutral"
    assert classify_buildup(5, 0) == "neutral"
    assert classify_buildup(0.0, 0.0) == "neutral"


def test_buildup_bias_collapse():
    assert buildup_bias("long_buildup_bullish") == "bullish"
    assert buildup_bias("short_covering") == "bullish"
    assert buildup_bias("short_buildup_bearish") == "bearish"
    assert buildup_bias("long_unwinding") == "bearish"
    assert buildup_bias("neutral") == "neutral"


def test_custom_matrix_labels_respected():
    m = {"price_up_oi_up": "CUSTOM_BULL"}
    assert classify_buildup(2, 3, m) == "CUSTOM_BULL"
