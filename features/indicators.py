"""
Technical-analysis indicator library — pure, point-in-time functions.

Every function takes an OHLCV DataFrame (columns: open/high/low/close/volume,
ideally a DatetimeIndex) and returns a pandas Series aligned to df.index where
the value at row i uses ONLY rows 0..i. Formulas are the standard ones (and
match the math already documented in the repo README), implemented directly on
pandas/numpy with no black-box TA dependency.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import FeatureSpec, register


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _wilder(s: pd.Series, n: int) -> pd.Series:
    """Wilder's smoothing == EMA with alpha = 1/n."""
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"] - pc).abs(),
    ], axis=1).max(axis=1)


# --------------------------------------------------------------------------- #
# TREND
# --------------------------------------------------------------------------- #
def sma(df, period=20, col="close"):
    return df[col].rolling(period).mean()


def ema(df, period=20, col="close"):
    return df[col].ewm(span=period, adjust=False).mean()


def wma(df, period=20, col="close"):
    w = np.arange(1, period + 1)
    return df[col].rolling(period).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def dma_distance(df, period=200, col="close"):
    """% distance of price above/below its N-day moving average."""
    ma = df[col].rolling(period).mean()
    return (df[col] - ma) / ma * 100.0


def macd_line(df, fast=12, slow=26, col="close"):
    return df[col].ewm(span=fast, adjust=False).mean() - df[col].ewm(span=slow, adjust=False).mean()


def macd_hist(df, fast=12, slow=26, signal=9, col="close"):
    line = macd_line(df, fast, slow, col)
    sig = line.ewm(span=signal, adjust=False).mean()
    return line - sig


def adx(df, period=14):
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    atr_ = _wilder(_true_range(df), period)
    plus_di = 100 * _wilder(pd.Series(plus_dm, index=df.index), period) / atr_
    minus_di = 100 * _wilder(pd.Series(minus_dm, index=df.index), period) / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _wilder(dx, period)


def supertrend_dir(df, period=10, multiplier=3.0):
    """Supertrend direction: +1 uptrend, -1 downtrend (point-in-time loop)."""
    atr_ = _wilder(_true_range(df), period)
    hl2 = (df["high"] + df["low"]) / 2
    upper = (hl2 + multiplier * atr_).to_numpy()
    lower = (hl2 - multiplier * atr_).to_numpy()
    close = df["close"].to_numpy()
    n = len(df)
    dirn = np.ones(n, dtype=float)
    fu, fl = upper.copy(), lower.copy()
    for i in range(1, n):
        fu[i] = upper[i] if (upper[i] < fu[i - 1] or close[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lower[i] if (lower[i] > fl[i - 1] or close[i - 1] < fl[i - 1]) else fl[i - 1]
        if close[i] > fu[i - 1]:
            dirn[i] = 1
        elif close[i] < fl[i - 1]:
            dirn[i] = -1
        else:
            dirn[i] = dirn[i - 1]
    return pd.Series(dirn, index=df.index)


# --------------------------------------------------------------------------- #
# MOMENTUM
# --------------------------------------------------------------------------- #
def rsi(df, period=14, col="close"):
    delta = df[col].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = _wilder(gain, period) / _wilder(loss, period).replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def stoch_k(df, period=14):
    ll = df["low"].rolling(period).min()
    hh = df["high"].rolling(period).max()
    return 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)


def roc(df, period=12, col="close"):
    return df[col].pct_change(period) * 100.0


def cci(df, period=20):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = tp.rolling(period).mean()
    md = (tp - sma_tp).abs().rolling(period).mean()
    return (tp - sma_tp) / (0.015 * md.replace(0, np.nan))


def williams_r(df, period=14):
    hh = df["high"].rolling(period).max()
    ll = df["low"].rolling(period).min()
    return -100 * (hh - df["close"]) / (hh - ll).replace(0, np.nan)


# --------------------------------------------------------------------------- #
# VOLATILITY
# --------------------------------------------------------------------------- #
def atr(df, period=14):
    return _wilder(_true_range(df), period)


def atr_pct(df, period=14):
    return _wilder(_true_range(df), period) / df["close"] * 100.0


def bollinger_width(df, period=20, k=2.0, col="close"):
    mid = df[col].rolling(period).mean()
    sd = df[col].rolling(period).std(ddof=0)
    return (2 * k * sd) / mid * 100.0


def bollinger_pctb(df, period=20, k=2.0, col="close"):
    mid = df[col].rolling(period).mean()
    sd = df[col].rolling(period).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    return (df[col] - lower) / (upper - lower).replace(0, np.nan)


def realized_vol(df, period=20, ann=252, col="close"):
    """Close-to-close annualised volatility (%)."""
    r = np.log(df[col] / df[col].shift(1))
    return r.rolling(period).std(ddof=0) * np.sqrt(ann) * 100.0


def parkinson_vol(df, period=20, ann=252):
    hl = np.log(df["high"] / df["low"]) ** 2
    var = hl.rolling(period).mean() / (4 * np.log(2))
    return np.sqrt(var * ann) * 100.0


def garman_klass_vol(df, period=20, ann=252):
    hl = 0.5 * np.log(df["high"] / df["low"]) ** 2
    co = (2 * np.log(2) - 1) * np.log(df["close"] / df["open"]) ** 2
    var = (hl - co).rolling(period).mean()
    return np.sqrt(var.clip(lower=0) * ann) * 100.0


# --------------------------------------------------------------------------- #
# VOLUME
# --------------------------------------------------------------------------- #
def rvol(df, period=20):
    return df["volume"] / df["volume"].rolling(period).mean()


def obv(df):
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def vwap(df):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    return (tp * df["volume"]).cumsum() / df["volume"].cumsum()


def session_vwap(df):
    """VWAP that resets each trading day (requires a DatetimeIndex)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    day = pd.Series(df.index, index=df.index)
    if np.issubdtype(np.asarray(df.index).dtype, np.datetime64):
        day = pd.Series(df.index.normalize(), index=df.index)
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vv = df["volume"].groupby(day).cumsum()
    return pv / vv


def cmf(df, period=20):
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng
    mfv = mfm * df["volume"]
    return mfv.rolling(period).sum() / df["volume"].rolling(period).sum()


# --------------------------------------------------------------------------- #
# default feature catalog (sensible parameterisations)
# --------------------------------------------------------------------------- #
def _register_defaults():
    specs = [
        FeatureSpec("ema_20", "trend", ema, {"period": 20}, 20),
        FeatureSpec("ema_50", "trend", ema, {"period": 50}, 50),
        FeatureSpec("sma_200", "trend", sma, {"period": 200}, 200),
        FeatureSpec("dma_dist_200", "trend", dma_distance, {"period": 200}, 200),
        FeatureSpec("macd_hist", "trend", macd_hist, {}, 35),
        FeatureSpec("adx_14", "trend", adx, {"period": 14}, 28),
        FeatureSpec("supertrend_dir", "trend", supertrend_dir, {"period": 10, "multiplier": 3.0}, 10),
        FeatureSpec("rsi_14", "momentum", rsi, {"period": 14}, 14),
        FeatureSpec("stoch_k_14", "momentum", stoch_k, {"period": 14}, 14),
        FeatureSpec("roc_12", "momentum", roc, {"period": 12}, 12),
        FeatureSpec("cci_20", "momentum", cci, {"period": 20}, 20),
        FeatureSpec("williams_r_14", "momentum", williams_r, {"period": 14}, 14),
        FeatureSpec("atr_14", "volatility", atr, {"period": 14}, 14),
        FeatureSpec("atr_pct_14", "volatility", atr_pct, {"period": 14}, 14),
        FeatureSpec("bb_width_20", "volatility", bollinger_width, {"period": 20}, 20),
        FeatureSpec("bb_pctb_20", "volatility", bollinger_pctb, {"period": 20}, 20),
        FeatureSpec("rvol_c2c_20", "volatility", realized_vol, {"period": 20}, 20),
        FeatureSpec("parkinson_20", "volatility", parkinson_vol, {"period": 20}, 20),
        FeatureSpec("garman_klass_20", "volatility", garman_klass_vol, {"period": 20}, 20),
        FeatureSpec("rvol_20", "volume", rvol, {"period": 20}, 20),
        FeatureSpec("obv", "volume", obv, {}, 1),
        FeatureSpec("vwap", "volume", vwap, {}, 1),
        FeatureSpec("cmf_20", "volume", cmf, {"period": 20}, 20),
    ]
    for s in specs:
        register(s)


_register_defaults()
