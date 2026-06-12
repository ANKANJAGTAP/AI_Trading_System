"""Per-instrument IV Rank/Percentile pure helpers (data/iv_history.py)."""
from data.iv_history import percentile_from_history, rank_from_history


def test_rank_at_extremes():
    hist = [10, 12, 14, 16, 18, 20]
    assert rank_from_history(hist[:-1] + [20]) == 100.0   # current == max
    assert rank_from_history(hist[:-1] + [10]) == 0.0      # current == min


def test_rank_midpoint():
    # range [10, 20], current 15 -> 50%
    assert rank_from_history([10, 20, 15]) == 50.0


def test_percentile_counts_below():
    # current = 18 (last); 2 of the 5 points (10, 12) are below it -> 40%
    assert percentile_from_history([10, 12, 20, 25, 18]) == 40.0


def test_insufficient_history_returns_none():
    assert rank_from_history([]) is None
    assert rank_from_history([12]) is None
    assert percentile_from_history(None) is None
