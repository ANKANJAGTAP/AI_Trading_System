"""#25 — honest backtest fill model: gap-through stops, limit targets, conservative
both-touched resolution, directional slippage. Pure, no I/O."""
from backtest.execution_model import (resolve_intrabar_exit, stop_fill_price,
                                       target_fill_price)


# ----------------------------------------------------- long (BUY) position
def test_long_gap_down_through_stop_fills_at_open_not_stop():
    # bar opens at 90, below the 95 stop -> filled at 90 (worse), reason stop
    reason, px = resolve_intrabar_exit("BUY", 95.0, 110.0, bar_open=90.0, bar_high=92.0, bar_low=88.0)
    assert reason == "stop" and px == 90.0


def test_long_intrabar_stop_fills_at_stop():
    reason, px = resolve_intrabar_exit("BUY", 95.0, 110.0, bar_open=100.0, bar_high=101.0, bar_low=94.0)
    assert reason == "stop" and px == 95.0


def test_long_gap_up_through_target_fills_at_open_better():
    # opens at 112, above the 110 target -> limit fills at the better 112
    reason, px = resolve_intrabar_exit("BUY", 95.0, 110.0, bar_open=112.0, bar_high=113.0, bar_low=111.0)
    assert reason == "target" and px == 112.0


def test_long_intrabar_target_fills_at_target():
    reason, px = resolve_intrabar_exit("BUY", 95.0, 110.0, bar_open=100.0, bar_high=111.0, bar_low=99.0)
    assert reason == "target" and px == 110.0


def test_long_both_touched_stop_wins():
    reason, px = resolve_intrabar_exit("BUY", 95.0, 110.0, bar_open=100.0, bar_high=111.0, bar_low=94.0)
    assert reason == "stop" and px == 95.0


def test_long_no_touch_returns_none():
    reason, px = resolve_intrabar_exit("BUY", 95.0, 110.0, bar_open=100.0, bar_high=105.0, bar_low=96.0)
    assert reason is None and px is None


# ----------------------------------------------------- short (SELL) position
def test_short_gap_up_through_stop_fills_at_open():
    reason, px = resolve_intrabar_exit("SELL", 105.0, 90.0, bar_open=110.0, bar_high=112.0, bar_low=108.0)
    assert reason == "stop" and px == 110.0


def test_short_intrabar_stop_fills_at_stop():
    reason, px = resolve_intrabar_exit("SELL", 105.0, 90.0, bar_open=100.0, bar_high=106.0, bar_low=99.0)
    assert reason == "stop" and px == 105.0


def test_short_gap_down_through_target_fills_at_open_better():
    reason, px = resolve_intrabar_exit("SELL", 105.0, 90.0, bar_open=88.0, bar_high=89.0, bar_low=87.0)
    assert reason == "target" and px == 88.0


def test_short_both_touched_stop_wins():
    reason, px = resolve_intrabar_exit("SELL", 105.0, 90.0, bar_open=100.0, bar_high=106.0, bar_low=89.0)
    assert reason == "stop" and px == 105.0


# ----------------------------------------------------- slippage direction
def test_stop_slippage_is_adverse():
    # long stop fills lower with slippage; short stop fills higher
    assert stop_fill_price("BUY", 100.0, 100.0, slippage_bps=10) < 100.0
    assert stop_fill_price("SELL", 100.0, 100.0, slippage_bps=10) > 100.0


def test_target_has_no_adverse_slippage():
    # a limit never fills worse than its price
    assert target_fill_price("BUY", 110.0, 105.0) == 110.0    # no gap -> exactly target
    assert target_fill_price("SELL", 90.0, 95.0) == 90.0


# ----------------------------------------------------- invariants
def test_fill_invariants_never_better_than_level_for_stop():
    """A stop never fills better than the stop for the trader; a target never fills
    worse than the target."""
    for o in (80.0, 95.0, 100.0, 115.0):
        long_stop = stop_fill_price("BUY", 95.0, o, slippage_bps=5)
        assert long_stop <= 95.0                       # long stop: at or below
        short_stop = stop_fill_price("SELL", 105.0, o, slippage_bps=5)
        assert short_stop >= 105.0                     # short stop: at or above
        long_tgt = target_fill_price("BUY", 110.0, o)
        assert long_tgt >= 110.0                       # long target: at or above
        short_tgt = target_fill_price("SELL", 90.0, o)
        assert short_tgt <= 90.0                        # short target: at or below
