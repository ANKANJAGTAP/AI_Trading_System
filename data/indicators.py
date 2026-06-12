"""Indicator library (spec §7): VWAP, ATR, EMA/SMA (incl. 200 DMA), RSI, RVOL.

Pure pandas/numpy functions over OHLCV frames (no external TA dependency, so the
math is transparent and testable). A `candles` frame is indexed by tz-aware `ts`
with columns: open, high, low, close, volume.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def dma_200(close: pd.Series) -> pd.Series:
    """200-day moving average (use on split/bonus-adjusted daily series)."""
    return sma(close, 200)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.ewm(alpha=1.0 / period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average Directional Index (Wilder): trend STRENGTH + direction.

    Returns a frame with columns adx / plus_di / minus_di. ADX >= ~20-25 => a real
    trend (direction given by which DI leads); below => range/chop. Used by the
    regime classifier instead of a bare price-vs-VWAP sign.
    """
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
                   axis=1).max(axis=1)
    alpha = 1.0 / period
    atr_ = tr.ewm(alpha=alpha, adjust=False).mean().replace(0, np.nan)
    plus_di = 100.0 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_
    minus_di = 100.0 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_ = dx.ewm(alpha=alpha, adjust=False).mean()
    return pd.DataFrame({"adx": adx_, "plus_di": plus_di, "minus_di": minus_di})


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def rvol(volume: pd.Series, period: int = 20) -> pd.Series:
    """Relative volume vs the trailing average."""
    avg = volume.rolling(period).mean()
    return volume / avg.replace(0, np.nan)


def vwap(df: pd.DataFrame) -> pd.Series:
    """Cumulative VWAP over the whole frame (use one session's data)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]
    return pv.cumsum() / df["volume"].cumsum().replace(0, np.nan)


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """Intraday VWAP that resets each trading day (anchored to the session)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]
    day = df.index.normalize()
    cum_pv = pv.groupby(day).cumsum()
    cum_vol = df["volume"].groupby(day).cumsum().replace(0, np.nan)
    return cum_pv / cum_vol


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD line / signal / histogram. Histogram sign + slope = momentum."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": macd_line - signal_line})


def bollinger(close: pd.Series, period: int = 20, k: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands (SMA midline +/- k population std)."""
    mid = sma(close, period)
    sd = close.rolling(period).std(ddof=0)
    return pd.DataFrame({"mid": mid, "upper": mid + k * sd, "lower": mid - k * sd})


def donchian(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Donchian channel (rolling high/low) — breakout reference."""
    upper = df["high"].rolling(period).max()
    lower = df["low"].rolling(period).min()
    return pd.DataFrame({"upper": upper, "lower": lower, "mid": (upper + lower) / 2.0})


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """SuperTrend (ATR bands). Returns columns supertrend / direction (+1 up, -1 down).
    In an uptrend the line tracks the lower band; it flips on a close through it."""
    hl2 = (df["high"] + df["low"]) / 2.0
    atr_ = atr(df, period)
    upper = (hl2 + multiplier * atr_).to_numpy()
    lower = (hl2 - multiplier * atr_).to_numpy()
    close = df["close"].to_numpy()
    n = len(df)
    fu = np.zeros(n)
    fl = np.zeros(n)
    st = np.zeros(n)
    direction = np.ones(n, dtype=int)
    for i in range(n):
        if i == 0:
            fu[i], fl[i], st[i], direction[i] = upper[i], lower[i], upper[i], -1
            continue
        fu[i] = upper[i] if (upper[i] < fu[i - 1] or close[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lower[i] if (lower[i] > fl[i - 1] or close[i - 1] < fl[i - 1]) else fl[i - 1]
        if st[i - 1] == fu[i - 1]:
            st[i] = fl[i] if close[i] > fu[i] else fu[i]
        else:
            st[i] = fu[i] if close[i] < fl[i] else fl[i]
        direction[i] = 1 if st[i] == fl[i] else -1
    return pd.DataFrame({"supertrend": st, "direction": direction}, index=df.index)


def anchored_vwap(df: pd.DataFrame, anchor) -> pd.Series:
    """VWAP anchored from `anchor` (a swing high/low or event ts) to the end."""
    sub = df[df.index >= anchor]
    if sub.empty:
        return pd.Series(dtype=float)
    typical = (sub["high"] + sub["low"] + sub["close"]) / 3.0
    pv = typical * sub["volume"]
    return pv.cumsum() / sub["volume"].cumsum().replace(0, np.nan)


def add_core_indicators(df: pd.DataFrame, intraday: bool = True) -> pd.DataFrame:
    """Attach the common indicator set used by the pipelines + chart overlays."""
    out = df.copy()
    out["ema9"] = ema(df["close"], 9)
    out["ema20"] = ema(df["close"], 20)
    out["sma50"] = sma(df["close"], 50)
    out["sma200"] = sma(df["close"], 200)
    out["rsi14"] = rsi(df["close"], 14)
    out["atr14"] = atr(df, 14)
    out["rvol20"] = rvol(df["volume"], 20)
    out["vwap"] = session_vwap(df) if intraday else vwap(df)
    bb = bollinger(df["close"], 20, 2.0)
    out["bb_upper"], out["bb_lower"] = bb["upper"], bb["lower"]
    st = supertrend(df, 10, 3.0)
    out["supertrend"], out["st_dir"] = st["supertrend"], st["direction"]
    out["macd_hist"] = macd(df["close"])["hist"]
    return out
