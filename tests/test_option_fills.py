"""#23 — option-leg fill realism: bid/ask crossing, spread cap, OI/volume gate."""
import math

from backtest.option_fills import (leg_fill, liquidity_ok, option_fill_price,
                                    spread_pct)


# ----------------------------------------------------- spread
def test_spread_pct_basic_and_invalid():
    assert abs(spread_pct(9.0, 11.0) - 0.2) < 1e-9          # (11-9)/10
    assert spread_pct(0.0, 5.0) == math.inf                 # non-positive bid
    assert spread_pct(11.0, 9.0) == math.inf                # crossed quote
    assert spread_pct(None, 5.0) == math.inf


# ----------------------------------------------------- liquidity
def test_liquidity_gate():
    assert liquidity_ok(1000, 500, min_oi=100, min_volume=100) is True
    assert liquidity_ok(50, 500, min_oi=100) is False        # OI too low
    assert liquidity_ok(1000, 10, min_volume=100) is False   # volume too low
    assert liquidity_ok(None, None) is True                  # no floors -> pass
    assert liquidity_ok(None, 500, min_oi=100) is False       # unknown OI fails closed


# ----------------------------------------------------- fill price
def test_fill_crosses_the_spread():
    # bid 9 / ask 11 (mid 10): BUY pays the ask, SELL hits the bid
    assert option_fill_price("BUY", 9.0, 11.0) == 11.0
    assert option_fill_price("SELL", 9.0, 11.0) == 9.0


def test_fill_slippage_is_adverse_both_sides():
    buy = option_fill_price("BUY", 9.0, 11.0, slippage_frac=0.1)   # +mid*0.1 = +1
    sell = option_fill_price("SELL", 9.0, 11.0, slippage_frac=0.1)
    assert buy == 12.0 and sell == 8.0
    assert buy > sell                                          # always buy higher than you sell


def test_buy_never_below_mid_sell_never_above():
    for bid, ask in ((1.0, 1.2), (50.0, 55.0), (0.5, 2.0)):
        mid = (bid + ask) / 2
        assert option_fill_price("BUY", bid, ask) >= mid
        assert option_fill_price("SELL", bid, ask) <= mid


# ----------------------------------------------------- combined leg gate
def test_leg_fill_tradable_when_tight_and_liquid():
    r = leg_fill("BUY", 9.9, 10.1, oi=5000, volume=2000,
                 max_spread_pct=0.25, min_oi=100, min_volume=100)
    assert r["tradable"] is True and r["fill_price"] == 10.1   # crosses to ask
    assert r["spread_pct"] < 0.05


def test_leg_fill_rejects_wide_spread():
    r = leg_fill("BUY", 8.0, 12.0, oi=5000, volume=2000, max_spread_pct=0.25)
    assert r["tradable"] is False and r["fill_price"] is None
    assert "spread" in r["reason"]


def test_leg_fill_rejects_illiquid_strike():
    r = leg_fill("SELL", 9.95, 10.05, oi=10, volume=5, min_oi=100, min_volume=100)
    assert r["tradable"] is False and "OI/volume" in r["reason"]


def test_leg_fill_rejects_unusable_quote():
    r = leg_fill("BUY", 0.0, 10.0)                            # no real bid
    assert r["tradable"] is False and r["spread_pct"] == math.inf


# ----------------------------------------------------- #23 synthetic spread model
def test_synthetic_spread_widens_for_otm_short_dte_high_iv():
    from backtest.option_fills import synthetic_spread_pct
    atm = synthetic_spread_pct(20000, 20000, 30, 0.15)
    otm = synthetic_spread_pct(20000, 21000, 30, 0.15)
    assert otm > atm                                          # OTM strike -> wider
    near = synthetic_spread_pct(20000, 20000, 2, 0.15)
    far = synthetic_spread_pct(20000, 20000, 45, 0.15)
    assert near > far                                         # short DTE -> wider
    hi_iv = synthetic_spread_pct(20000, 20000, 30, 0.40)
    assert hi_iv > atm                                       # high IV -> wider
    assert synthetic_spread_pct(20000, 35000, 1, 5.0) <= 0.5  # capped
