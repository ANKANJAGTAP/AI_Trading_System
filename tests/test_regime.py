"""ADX-based regime classifier (engine/context_builder.classify_regime)."""
import numpy as np
import pandas as pd

from engine.context_builder import classify_regime


def _frame(closes):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "open": closes, "high": closes + 0.5, "low": closes - 0.5,
        "close": closes, "volume": np.full(len(closes), 1000),
    })


def test_strong_uptrend_is_trending_up():
    df = _frame(np.arange(100, 160, 1.0))
    assert classify_regime(df, last_price=159.0, vwap=140.0) == "trending_up"


def test_strong_downtrend_is_trending_down():
    df = _frame(np.arange(160, 100, -1.0))
    assert classify_regime(df, last_price=101.0, vwap=130.0) == "trending_down"


def test_flat_tape_is_choppy():
    chop = [100 + (0.2 if i % 2 else -0.2) for i in range(60)]
    df = _frame(chop)
    # price sitting on VWAP, no trend -> choppy (breakouts disabled)
    assert classify_regime(df, last_price=100.0, vwap=100.0) == "choppy"


def test_di_vwap_disagreement_is_choppy():
    # uptrend by DI but price below VWAP -> disagreement -> choppy
    df = _frame(np.arange(100, 160, 1.0))
    assert classify_regime(df, last_price=120.0, vwap=200.0) == "choppy"
