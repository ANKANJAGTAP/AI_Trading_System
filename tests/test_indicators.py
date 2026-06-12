"""ADX indicator (data/indicators.py)."""
import numpy as np
import pandas as pd

from data import indicators


def _frame(closes):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "open": closes,
        "high": closes + 0.5,
        "low": closes - 0.5,
        "close": closes,
        "volume": np.full(len(closes), 1000),
    })


def test_adx_columns_and_uptrend_di():
    df = _frame(np.arange(100, 160, 1.0))  # steady uptrend
    a = indicators.adx(df, 14)
    assert set(a.columns) == {"adx", "plus_di", "minus_di"}
    last = a.iloc[-1]
    assert last["plus_di"] > last["minus_di"]   # +DI leads in an uptrend
    assert last["adx"] > 20                       # strong trend registers


def test_adx_downtrend_di():
    df = _frame(np.arange(160, 100, -1.0))  # steady downtrend
    last = indicators.adx(df, 14).iloc[-1]
    assert last["minus_di"] > last["plus_di"]


def test_adx_choppy_is_weak():
    chop = [100 + (1 if i % 2 else -1) for i in range(60)]
    last = indicators.adx(_frame(chop), 14).iloc[-1]
    assert last["adx"] < 25   # no real trend


# --- Phase 2 indicator pack ---------------------------------------------------
def test_macd_uptrend_positive_hist():
    m = indicators.macd(pd.Series(np.linspace(100, 160, 80)))
    assert set(m.columns) == {"macd", "signal", "hist"}
    assert m["hist"].iloc[-1] > 0


def test_bollinger_order_and_width():
    bb = indicators.bollinger(pd.Series(np.linspace(100, 160, 60)), 20, 2.0)
    last = bb.iloc[-1]
    assert last["upper"] > last["mid"] > last["lower"]


def test_supertrend_direction():
    up = _frame(np.linspace(100, 160, 80))
    down = _frame(np.linspace(160, 100, 80))
    assert int(indicators.supertrend(up)["direction"].iloc[-1]) == 1
    assert int(indicators.supertrend(down)["direction"].iloc[-1]) == -1


def test_donchian_bounds():
    dc = indicators.donchian(_frame(np.linspace(100, 160, 60)), 20)
    last = dc.iloc[-1]
    assert last["upper"] >= last["mid"] >= last["lower"]


def test_anchored_vwap_within_range():
    df = _frame(np.linspace(100, 160, 60))
    av = indicators.anchored_vwap(df, df.index[30])
    assert len(av) == 30
    assert 100 <= float(av.iloc[-1]) <= 160


def test_add_core_indicators_has_pack_columns():
    df = _frame(np.linspace(100, 160, 80))
    # session_vwap needs a datetime index (production frames are tz-aware).
    df.index = pd.date_range("2026-01-01 09:15", periods=len(df), freq="5min", tz="Asia/Kolkata")
    cols = indicators.add_core_indicators(df, intraday=True).columns
    for c in ("bb_upper", "bb_lower", "supertrend", "st_dir", "macd_hist", "vwap"):
        assert c in cols
