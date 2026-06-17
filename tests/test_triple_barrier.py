"""Tests for triple-barrier labeling: which barrier the forward path hits first,
stop-first on a straddle, vertical timeout, short side, and batch no-look-ahead."""
from research.triple_barrier import label_events, triple_barrier_label

# entry 100, pt 2% -> 102, sl 1% -> 99 (for a long)
_KW = dict(pt_pct=0.02, sl_pct=0.01, max_holding=5)


# ----------------------------------------------------- long (BUY)
def test_long_profit_first():
    r = triple_barrier_label([101, 102.5], [100, 101], 100.0, "BUY", **_KW)
    assert r["label"] == 1 and r["barrier"] == "pt" and r["holding"] == 2
    assert r["exit_price"] == 102.0


def test_long_stop_first():
    r = triple_barrier_label([101, 101], [100, 98], 100.0, "BUY", **_KW)
    assert r["label"] == -1 and r["barrier"] == "sl" and r["holding"] == 2
    assert r["exit_price"] == 99.0


def test_long_straddle_resolves_to_stop():
    # first bar hits BOTH 102 and 99 -> stop wins (conservative)
    r = triple_barrier_label([103], [98], 100.0, "BUY", **_KW)
    assert r["label"] == -1 and r["barrier"] == "sl" and r["holding"] == 1


def test_long_vertical_timeout():
    r = triple_barrier_label([101, 101, 101], [100, 100, 100], 100.0, "BUY",
                             pt_pct=0.02, sl_pct=0.01, max_holding=3)
    assert r["label"] == 0 and r["barrier"] == "vertical" and r["holding"] == 3
    assert r["exit_price"] is None


def test_horizon_capped_by_available_bars():
    r = triple_barrier_label([101, 101], [100, 100], 100.0, "BUY",
                             pt_pct=0.02, sl_pct=0.01, max_holding=10)
    assert r["label"] == 0 and r["holding"] == 2          # only 2 bars exist


def test_no_forward_bars_is_timeout_zero_holding():
    r = triple_barrier_label([], [], 100.0, "BUY", **_KW)
    assert r["label"] == 0 and r["holding"] == 0 and r["barrier"] == "vertical"


# ----------------------------------------------------- short (SELL)
def test_short_profit_on_fall():
    # short profits when price falls to 98 (pt) before rising to 102 (sl)
    r = triple_barrier_label([100, 99], [99, 97.5], 100.0, "SELL", **_KW)
    assert r["label"] == 1 and r["barrier"] == "pt" and r["exit_price"] == 98.0


def test_short_stop_on_rise():
    # short stop is at 101 (entry +1%); rises through it on bar 2
    r = triple_barrier_label([100.5, 102.5], [100, 101], 100.0, "SELL", **_KW)
    assert r["label"] == -1 and r["barrier"] == "sl" and r["exit_price"] == 101.0
    assert r["holding"] == 2


# ----------------------------------------------------- batch / no look-ahead
def test_label_events_uses_only_forward_bars():
    highs = [100.0, 103.0, 100.0, 100.0, 100.0]
    lows = [100.0, 100.0, 100.0, 100.0, 100.0]
    # event at idx 0, entry 100: forward starts at idx 1 (high 103 -> pt at holding 1)
    out = label_events(highs, lows, [{"idx": 0, "side": "BUY", "entry": 100.0}], **_KW)
    assert out[0]["label"] == 1 and out[0]["holding"] == 1
    # event entered on the last bar has no forward bars -> timeout
    last = label_events(highs, lows, [{"idx": 4, "side": "BUY", "entry": 100.0}], **_KW)
    assert last[0]["label"] == 0 and last[0]["holding"] == 0


def test_label_values_are_valid_and_event_fields_preserved():
    highs = [100 + i for i in range(20)]
    lows = [100 - i * 0.1 for i in range(20)]
    events = [{"idx": i, "side": "BUY", "entry": float(highs[i])} for i in range(0, 15, 3)]
    out = label_events(highs, lows, events, pt_pct=0.03, sl_pct=0.02, max_holding=6)
    for o in out:
        assert o["label"] in (-1, 0, 1)
        assert o["holding"] >= 0
        assert "idx" in o and "entry" in o            # original event fields preserved
