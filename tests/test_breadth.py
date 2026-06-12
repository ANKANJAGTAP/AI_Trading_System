"""Market breadth classification (data/breadth.py)."""
from data.breadth import classify_breadth


def test_bullish_breadth():
    b = classify_breadth([1.0, 2.0, 0.5, 3.0, -0.2])  # 4 up, 1 down
    assert b["advances"] == 4 and b["declines"] == 1
    assert b["bias"] == "bullish"
    assert b["adv_pct"] == 80.0


def test_bearish_breadth():
    b = classify_breadth([-1.0, -2.0, -0.5, 0.3])  # 3 down, 1 up
    assert b["declines"] == 3 and b["advances"] == 1
    assert b["bias"] == "bearish"


def test_neutral_breadth():
    b = classify_breadth([1.0, -1.0, 0.5, -0.5])  # 2 up, 2 down
    assert b["bias"] == "neutral"
    assert b["ad_ratio"] == 1.0


def test_empty_breadth():
    b = classify_breadth([])
    assert b["total"] == 0 and b["adv_pct"] == 0.0 and b["bias"] == "neutral"


def test_flat_counts_with_eps():
    b = classify_breadth([0.0, 0.01, -0.01, 2.0], eps=0.05)  # first three flat
    assert b["flat"] == 3 and b["advances"] == 1
