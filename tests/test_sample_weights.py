"""§10 Phase 2 — sample weights (label uniqueness + time decay)."""
from backtest.sample_weights import time_decay_weights, uniqueness_weights


def test_time_decay_linear():
    w = time_decay_weights(5, last=0.5)
    assert w == [0.5, 0.625, 0.75, 0.875, 1.0]               # oldest .5 -> newest 1.0
    assert time_decay_weights(1) == [1.0]
    assert time_decay_weights(0) == []


def test_time_decay_clamps_negative_last():
    w = time_decay_weights(4, last=-1.0)
    assert w[0] == 0.0 and w[-1] == 1.0 and all(x >= 0.0 for x in w)


def test_uniqueness_isolated_labels_are_one():
    assert uniqueness_weights([(0, 1), (2, 3)]) == [1.0, 1.0]


def test_uniqueness_full_overlap_is_half():
    assert uniqueness_weights([(0, 3), (0, 3)]) == [0.5, 0.5]


def test_uniqueness_partial_overlap():
    w = uniqueness_weights([(0, 2), (1, 3)])
    assert all(abs(x - 0.6667) < 1e-3 for x in w)            # mean(1/concurrency)


def test_empty():
    assert uniqueness_weights([]) == []
