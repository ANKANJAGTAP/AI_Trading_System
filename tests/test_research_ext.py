"""Feature-discrimination report + F&O-backtest pure helpers + trade-quality features."""
from datetime import date

from backtest.fno_engine import _choose_dte, _strike_step, slippage_cost, structure_pnl
from research.discrimination import discriminate
from research.features import extract_features
from strategies.base import Signal
from strategies.fno import FnoContext
from strategies.intraday import IntradayContext


# --- feature discrimination ---------------------------------------------------
def test_discriminate_finds_separating_feature():
    samples = []
    for i in range(40):
        win = i % 2
        samples.append({"features": {"regime": 1.0 if win else 0.0, "noise": (i % 3) * 0.1},
                        "label": win})
    d = discriminate(samples, min_per_bucket=3)
    feats = {f["feature"]: f for f in d["features"]}
    assert feats["regime"]["lift"] > 0.5     # perfectly separating feature shows big lift


def test_discriminate_no_edge_low_lift():
    # label random, feature constant -> reported as constant (lift 0), no real signal
    samples = [{"features": {"g": 0.9}, "label": i % 2} for i in range(40)]
    d = discriminate(samples, min_per_bucket=3)
    assert all(abs(f["lift"]) < 0.3 for f in d["features"])


def test_discriminate_verdict_needs_data():
    samples = [{"features": {"g": float(i % 2)}, "label": i % 2} for i in range(30)]
    assert discriminate(samples)["verdict"] == "insufficient_data"   # n < 100


# --- F&O backtest pure helpers ------------------------------------------------
def test_strike_step_heuristic():
    assert _strike_step("NIFTY", 23000) == 50
    assert _strike_step("BANKNIFTY", 50000) == 100
    assert _strike_step("ANYSTOCK", 900) == 20
    assert _strike_step("ANYSTOCK", 1265) == 50


def test_choose_dte_by_iv_regime():
    cfg = {"iv_rank": {"low_max": 20, "high_min": 70},
           "dte": {"weekly_buy": [3, 10], "credit_sell": [15, 45], "swing_buy": [20, 45]}}
    assert _choose_dte(10, cfg) == 6     # low IV -> weekly
    assert _choose_dte(80, cfg) == 30    # high IV -> credit
    assert _choose_dte(50, cfg) == 32    # mid -> swing


def test_equity_trade_quality_features():
    ctx = IntradayContext(last_price=100, or_high=101, or_low=99, vwap=99.5, rvol=2.0,
                          daily_adv=1e6, spread_pct=0.05, gap_pct=0.6, regime="trending_up",
                          atr_pct=1.8, rel_strength=3.2)
    sig = Signal("intraday_stocks", {}, "BUY", "orb", 100, 99, 102)
    f = extract_features("intraday_stocks", ctx, 0.7, signal=sig)
    assert f["atr_pct"] == 1.8 and f["rel_strength"] == 3.2
    assert f["reward_risk"] == 2.0       # (102-100)/(100-99)
    assert f["stop_pct"] == 1.0          # (100-99)/100*100


def test_fno_trade_quality_features():
    ctx = FnoContext(spot=23000, iv=0.15, iv_rank=80, dte=25, direction="bullish",
                     lot_size=65, expiry=date(2026, 7, 1), strike_step=50)
    sig = Signal("fno", {}, "BUY", "bull_put_credit", 23000, 0, 0,
                 detail={"structure": {"type": "bull_put_credit", "short_leg": 22800,
                                       "long_leg": 22700, "max_loss_per_lot": 3000,
                                       "net_credit": 25.0, "opt": "PE"}})
    f = extract_features("fno", ctx, 0.7, signal=sig)
    assert f["iv_rank"] == 80 and f["dir_bull"] == 1.0
    assert f["is_credit"] == 1.0 and f["is_condor"] == 0.0
    assert round(f["moneyness_pct"], 2) == -0.87          # (22800-23000)/23000*100
    # WIDTH-aware reward:risk — width from the actual legs (100), not the strike step
    assert round(f["reward_risk"], 3) == round((100 * 65 - 3000) / 3000, 3)
    assert round(f["credit_ratio"], 3) == 0.25            # 25 credit / 100 width


def test_structure_pnl_credit_spread_decays_to_profit():
    # short put spread (net credit): SELL 23000PE, BUY 22900PE; spot well above strikes.
    legs = [("PE", 23000, "SELL", 100.0), ("PE", 22900, "BUY", 60.0)]
    p_far = structure_pnl(legs, qty=75, spot=23200, dte_days=20, iv=0.15)
    p_near = structure_pnl(legs, qty=75, spot=23200, dte_days=0.5, iv=0.15)
    assert p_near > p_far          # theta decay helps the net-short-premium spread
    assert p_near > 0              # OTM puts expire worthless -> credit captured


def test_slippage_cost_positive_and_scales():
    legs = [("PE", 23000, "SELL", 100.0), ("PE", 22900, "BUY", 60.0)]
    c1 = slippage_cost(legs, qty=75, spot=23000, dte_days=20, iv=0.15, slip_pct=1.5)
    c0 = slippage_cost(legs, qty=75, spot=23000, dte_days=20, iv=0.15, slip_pct=0.0)
    assert c0 == 0.0 and c1 > 0.0            # zero slippage -> no cost; positive otherwise
    c2 = slippage_cost(legs, qty=75, spot=23000, dte_days=20, iv=0.15, slip_pct=3.0)
    assert round(c2, 2) == round(2 * c1, 2)   # cost scales linearly with slip %
