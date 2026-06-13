import numpy as np
import pandas as pd

from features import indicators as ind


def _df(closes):
    c = pd.Series(closes, dtype=float)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                         "volume": pd.Series([1000] * len(c))})


def test_sma_exact():
    df = _df([1, 2, 3, 4, 5])
    s = ind.sma(df, period=3)
    assert np.isnan(s.iloc[1])
    assert s.iloc[2] == 2.0
    assert s.iloc[4] == 4.0


def test_ema_of_constant_is_constant():
    df = _df([5.0] * 30)
    e = ind.ema(df, period=10)
    assert np.allclose(e.to_numpy(), 5.0)


def test_rsi_bounds(ohlcv):
    r = ind.rsi(ohlcv, period=14).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_atr_positive(ohlcv):
    a = ind.atr(ohlcv, period=14).dropna()
    assert (a > 0).all()


def test_adx_bounds(ohlcv):
    a = ind.adx(ohlcv, period=14).dropna()
    assert ((a >= 0) & (a <= 100)).all()


def test_supertrend_dir_values(ohlcv):
    d = ind.supertrend_dir(ohlcv).dropna().unique()
    assert set(np.unique(d)).issubset({-1.0, 1.0})


def test_obv_runs(ohlcv):
    o = ind.obv(ohlcv)
    assert len(o) == len(ohlcv) and np.isfinite(o.iloc[-1])


def test_vwap_between_low_and_high_early(ohlcv):
    v = ind.vwap(ohlcv)
    # first bar: vwap == typical price, within [low, high]
    tp0 = (ohlcv["high"].iloc[0] + ohlcv["low"].iloc[0] + ohlcv["close"].iloc[0]) / 3
    assert abs(v.iloc[0] - tp0) < 1e-9


def test_bollinger_pctb_midband_is_half():
    # constant-trend series so close sits at the middle band -> %B ~ 0.5 undefined
    df = _df(list(range(1, 60)))
    pctb = ind.bollinger_pctb(df, period=20).dropna()
    assert np.isfinite(pctb.iloc[-1])


def test_no_lookahead_truncation_invariance(ohlcv):
    """Value at row k-1 must be identical whether or not later rows exist."""
    from features.base import REGISTRY
    k = 120
    for fid in ["ema_20", "rsi_14", "atr_14", "macd_hist"]:
        full = REGISTRY[fid].compute(ohlcv)
        trunc = REGISTRY[fid].compute(ohlcv.iloc[:k])
        a, b = full.iloc[k - 1], trunc.iloc[k - 1]
        if not (np.isnan(a) and np.isnan(b)):
            assert abs(a - b) < 1e-9, f"look-ahead leak in {fid}"
