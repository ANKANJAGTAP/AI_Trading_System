"""Phase 3 pure logic: GEX, volume profile, book imbalance, risk circuits."""
import numpy as np
import pandas as pd

from data.gex import compute_gex
from data.orderflow import book_imbalance
from data.volume_profile import volume_profile
from risk.circuits import drawdown_breached, profit_lock_breached, should_disable_sleeve


# --- 3.1 GEX -----------------------------------------------------------------
def test_gex_sign_and_walls():
    rows = [
        {"strike": 100, "call": {"gamma": 0.03, "oi": 5000}, "put": {"gamma": 0.01, "oi": 1000}},
        {"strike": 110, "call": {"gamma": 0.01, "oi": 1000}, "put": {"gamma": 0.03, "oi": 5000}},
    ]
    g = compute_gex(rows, spot=105, contract_size=50)
    # strike 100 is call-heavy (+gex), strike 110 is put-heavy (-gex)
    assert g["call_wall"] == 100 and g["put_wall"] == 110
    assert g["regime"] in ("positive_gamma", "negative_gamma")
    assert len(g["by_strike"]) == 2


def test_gex_positive_when_calls_dominate():
    rows = [{"strike": 100, "call": {"gamma": 0.05, "oi": 9000}, "put": {"gamma": 0.01, "oi": 100}}]
    assert compute_gex(rows, 100, 50)["regime"] == "positive_gamma"


def test_gex_handles_missing_legs():
    g = compute_gex([{"strike": 100, "call": None, "put": None}], 100, 50)
    assert g["net_gex"] == 0.0


# --- 3.3 volume profile ------------------------------------------------------
def _frame(prices, vols):
    p = np.asarray(prices, dtype=float)
    return pd.DataFrame({"open": p, "high": p + 1, "low": p - 1, "close": p, "volume": vols})


def test_volume_profile_poc_at_busiest_price():
    # heavy volume clustered around 150
    prices = [100, 110, 150, 150, 150, 120, 130]
    vols = [100, 100, 5000, 5000, 5000, 100, 100]
    vp = volume_profile(_frame(prices, vols), bins=10)
    assert vp["val"] <= vp["poc"] <= vp["vah"]
    assert 148 <= vp["poc"] <= 152


def test_volume_profile_empty():
    vp = volume_profile(pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))
    assert vp["poc"] is None and vp["bins"] == []


# --- 3.4 book imbalance ------------------------------------------------------
def test_book_imbalance_bias():
    assert book_imbalance([{"quantity": 900}], [{"quantity": 100}])["bias"] == "buy"
    assert book_imbalance([{"quantity": 100}], [{"quantity": 900}])["bias"] == "sell"
    assert book_imbalance([{"quantity": 500}], [{"quantity": 500}])["bias"] == "neutral"


def test_book_imbalance_empty():
    b = book_imbalance([], [])
    assert b["imbalance"] == 0.0 and b["bias"] == "neutral"


# --- 3.2 circuits ------------------------------------------------------------
def test_drawdown_breached():
    assert drawdown_breached(peak_pnl=10000, current_pnl=1000, capital=100_000, max_dd_pct=8.0)
    assert not drawdown_breached(peak_pnl=10000, current_pnl=5000, capital=100_000, max_dd_pct=8.0)
    assert not drawdown_breached(10000, 1000, capital=0, max_dd_pct=8.0)   # no capital -> no trip


def test_should_disable_sleeve():
    assert should_disable_sleeve([-0.5] * 12, min_trades=10, expectancy_floor=-0.2)
    assert not should_disable_sleeve([0.3] * 12, min_trades=10, expectancy_floor=-0.2)
    assert not should_disable_sleeve([-0.9] * 5, min_trades=10, expectancy_floor=-0.2)  # too few


def test_profit_lock():
    cap = 1_000_000
    # today's case: peak +110k, give back to +66k (40%) -> with 35% floor (71.5k), trips
    assert profit_lock_breached(110_000, 66_000, cap, trigger_pct=2.0, max_giveback_pct=35.0)
    # still near the peak -> no trip
    assert not profit_lock_breached(110_000, 100_000, cap, trigger_pct=2.0, max_giveback_pct=35.0)
    # peak below the arm trigger (2% = 20k) -> never trips
    assert not profit_lock_breached(15_000, 1_000, cap, trigger_pct=2.0, max_giveback_pct=35.0)
    # no peak profit -> no trip
    assert not profit_lock_breached(0, -5_000, cap, trigger_pct=2.0, max_giveback_pct=35.0)
