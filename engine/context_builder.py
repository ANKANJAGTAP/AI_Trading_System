"""Build pipeline contexts from market data.

TD-1: the context-construction math is split into PURE functions over DataFrames
(`*_from_frames`) and thin LIVE wrappers that load frames from the DB/quotes. The
backtest engine drives the exact same pure functions over historical frames, so
backtest and live decisions are identical by construction (no reimplementation).

Best-effort: returns None if data isn't sufficient yet (e.g. before the opening
range forms), and the caller simply skips that instrument this cycle.
"""
from __future__ import annotations

from datetime import datetime
from datetime import time as dtime

import pandas as pd

from common.logging import get_logger
from common.market_time import IST, is_within, now_ist, today_ist
from data import features, indicators
from data.iv_history import iv_change_for, iv_rank_for
from data.oi import classify_buildup
from data.option_chain import atm_strike, nearest_expiry, resolve_option, strike_step, vix_iv_rank
from data.options import implied_vol
from data.store import load_candles_df
from strategies.fno import FnoContext
from strategies.intraday import IntradayContext

log = get_logger("context_builder")


# --------------------------------------------------------------------------- #
# Intraday — pure context construction (shared by live + backtest)
# --------------------------------------------------------------------------- #
def classify_regime(df_5m: pd.DataFrame, last_price: float, vwap: float,
                    regime_cfg: dict | None = None) -> str:
    """ADX-based regime: a real trend needs ADX >= adx_trend_min (direction from the
    leading DI, confirmed by the VWAP side); otherwise choppy (breakouts disabled).
    Falls back to the VWAP sign when ADX can't be computed (too few bars)."""
    cfg = regime_cfg or {}
    period = int(cfg.get("adx_period", 14))
    trend_min = float(cfg.get("adx_trend_min", 20))
    if len(df_5m) >= period * 2:
        a = indicators.adx(df_5m, period).iloc[-1]
        adx_val, pdi, mdi = a["adx"], a["plus_di"], a["minus_di"]
        if adx_val == adx_val and adx_val >= trend_min:   # NaN-safe
            up = pdi >= mdi
            # require price on the same side of VWAP as the DI vote (agreement)
            if up and last_price >= vwap:
                return "trending_up"
            if not up and last_price <= vwap:
                return "trending_down"
            return "choppy"  # DI/VWAP disagree -> treat as chop
    # fallback: VWAP sign with a small neutral band
    if vwap > 0 and abs(last_price - vwap) / vwap <= 0.0015:
        return "choppy"
    return "trending_up" if last_price > vwap else "trending_down"


def _pct_return(df: pd.DataFrame, n: int) -> float:
    if df is None or df.empty or len(df) <= n:
        return 0.0
    prev = float(df["close"].iloc[-1 - n])
    return (float(df["close"].iloc[-1]) / prev - 1.0) * 100.0 if prev else 0.0


def intraday_context_from_frames(df_5m: pd.DataFrame, df_day: pd.DataFrame, now: datetime,
                                 india_vix: float = 15.0, sector_strong: bool = True,
                                 regime_cfg: dict | None = None,
                                 index_df: pd.DataFrame | None = None) -> IntradayContext | None:
    """Pure IntradayContext from raw frames as-of `now`. No DB, no look-ahead: the
    caller must pass frames already sliced to ts <= now."""
    if df_5m is None or df_5m.empty:
        return None
    idx = df_5m.index.tz_convert(IST)
    today = now.date()
    today_df = df_5m[idx.date == today]
    if len(today_df) == 0:
        return None
    tidx = today_df.index.tz_convert(IST)
    or_mask = [dtime(9, 15) <= t.time() < dtime(9, 30) for t in tidx]
    or_df = today_df[or_mask]
    if len(or_df) == 0:
        return None  # opening range not formed yet

    or_high, or_low = float(or_df["high"].max()), float(or_df["low"].min())
    vwap = float(indicators.session_vwap(today_df).iloc[-1])
    rv = indicators.rvol(today_df["volume"], 20).iloc[-1]
    rvol = float(rv) if rv == rv else float(  # NaN check
        today_df["volume"].iloc[-1] / max(1.0, today_df["volume"].mean()))
    last_price = float(today_df["close"].iloc[-1])

    daily_adv = float(df_day["volume"].mean()) if df_day is not None and not df_day.empty else 0.0
    gap_pct = 0.0
    if df_day is not None and len(df_day) >= 2:
        prev_close = float(df_day["close"].iloc[-2])
        if prev_close:
            gap_pct = (float(today_df["open"].iloc[0]) - prev_close) / prev_close * 100

    regime = classify_regime(df_5m, last_price, vwap, regime_cfg)
    # Momentum confirmation (computed on the continuous 5m frame).
    macd_hist = st_dir = 0.0
    if len(df_5m) >= 35:
        try:
            macd_hist = float(indicators.macd(df_5m["close"])["hist"].iloc[-1])
            st_dir = int(indicators.supertrend(df_5m)["direction"].iloc[-1])
        except Exception:
            macd_hist, st_dir = 0.0, 0
    # Normalised volatility (daily ATR%) + relative strength vs the index (20d).
    atr_pct = 0.0
    if df_day is not None and len(df_day) >= 15 and last_price:
        try:
            atr_pct = float(indicators.atr(df_day, 14).iloc[-1]) / last_price * 100.0
        except Exception:
            atr_pct = 0.0
    rel_strength = _pct_return(df_day, 20) - _pct_return(index_df, 20) if index_df is not None else 0.0
    return IntradayContext(
        last_price=last_price, or_high=or_high, or_low=or_low, vwap=vwap, rvol=rvol,
        daily_adv=daily_adv, spread_pct=0.05, gap_pct=gap_pct, regime=regime,
        sector_strong=sector_strong, now_window_ok=is_within("09:30", "14:30", at=now),
        macd_hist=macd_hist, st_dir=int(st_dir), atr_pct=round(atr_pct, 3),
        rel_strength=round(rel_strength, 3),
    )


async def _index_daily():
    """NIFTY-50 daily frame for relative-strength (cached per trading day)."""
    from data.instruments import get_token
    tok = await get_token("NSE:NIFTY 50")
    return await load_candles_df(tok, "day", 60) if tok else None


async def build_intraday_context(instrument_token: int, india_vix: float = 15.0,
                                 sector_strong: bool = True,
                                 regime_cfg: dict | None = None) -> IntradayContext | None:
    """Live wrapper: load frames, then build via the pure function. Cached per closed
    5m candle (TD-2) so the slow loop doesn't recompute every ~60s cycle."""
    try:
        df = await load_candles_df(instrument_token, "5m", 400)
        if df.empty:
            return None
        last_ts = df.index[-1]

        async def _factory():
            daily = await load_candles_df(instrument_token, "day", 60)
            index_df = await _index_daily()
            return intraday_context_from_frames(df, daily, now_ist(), india_vix,
                                                sector_strong, regime_cfg, index_df=index_df)

        return await features.get_or_compute(instrument_token, "5m", last_ts, _factory)
    except Exception as exc:
        log.warning("build_intraday_context_failed", token=instrument_token, error=str(exc))
        return None


# --------------------------------------------------------------------------- #
# F&O — live context (OI buildup wired in)
# --------------------------------------------------------------------------- #
def daily_direction_from_df(df_day: pd.DataFrame, spot: float, band: float = 0.005) -> str:
    if df_day is None or df_day.empty or len(df_day) < 20:
        return "neutral"
    sma20 = float(df_day["close"].tail(20).mean())
    if spot > sma20 * (1 + band):
        return "bullish"
    if spot < sma20 * (1 - band):
        return "bearish"
    return "neutral"


async def _daily_direction(underlying_token: int, spot: float, band: float = 0.005) -> str:
    return daily_direction_from_df(await load_candles_df(underlying_token, "day", 60), spot, band)


async def _price_oi_change(token: int) -> tuple[float, float]:
    """(close_change, oi_change) over the last two closed candles for an option token."""
    df = await load_candles_df(token, "5m", 3)
    if df.empty or len(df) < 2 or "oi" not in df.columns:
        return 0.0, 0.0
    close = df["close"].astype(float)
    oi = df["oi"].fillna(0).astype(float)
    return float(close.iloc[-1] - close.iloc[-2]), float(oi.iloc[-1] - oi.iloc[-2])


async def build_fno_context(adapter, governor, name: str, underlying_key: str,
                            underlying_token: int, fno_cfg: dict, risk_free: float = 0.065):
    """Live FnoContext for an underlying. IV-rank (VIX proxy) is computed FIRST so the
    expiry is chosen in the DTE window the pipeline's IV-regime will require."""
    try:
        # Per-name IV Rank when enough history exists (Phase 2.2); else INDIA VIX proxy.
        ivr = await iv_rank_for(name)
        if ivr is None:
            ivr = await vix_iv_rank()
        if ivr is None:
            ivr = 50.0
        th, dte_cfg = fno_cfg.get("iv_rank", {}), fno_cfg.get("dte", {})
        if ivr < th.get("low_max", 20):
            window = dte_cfg.get("weekly_buy", [3, 10])
        elif ivr > th.get("high_min", 70):
            window = dte_cfg.get("credit_sell", [15, 45])
        else:
            window = dte_cfg.get("swing_buy", [20, 45])
        exp = await nearest_expiry(name, window[0], window[1])
        if not exp:
            return None
        expiry, dte = exp

        q = await governor.call("quote", adapter.quote, [underlying_key])
        spot = float(q[underlying_key]["last_price"])
        step = await strike_step(name, expiry)
        if not step:
            return None
        atm = atm_strike(spot, step)
        ce = await resolve_option(name, expiry, atm, "CE")
        pe = await resolve_option(name, expiry, atm, "PE")
        if not ce or not pe:
            return None

        ce_key, pe_key = f"NFO:{ce['tradingsymbol']}", f"NFO:{pe['tradingsymbol']}"
        oq = await governor.call("quote", adapter.quote, [ce_key, pe_key])
        ce_q, pe_q = oq.get(ce_key, {}), oq.get(pe_key, {})
        t = max(dte, 1) / 365.0
        ivs = []
        for qd, opt in ((ce_q, "CE"), (pe_q, "PE")):
            ltp = qd.get("last_price")
            if ltp:
                v = implied_vol(float(ltp), spot, atm, t, risk_free, opt)
                if v and v > 0:
                    ivs.append(v)
        iv = sum(ivs) / len(ivs) if ivs else 0.15

        direction = await _daily_direction(underlying_token, spot)
        ce_oi, pe_oi = float(ce_q.get("oi") or 0), float(pe_q.get("oi") or 0)
        pcr = (pe_oi / ce_oi) if ce_oi > 0 else 1.0
        pcr_signal = "bullish" if pcr > 1.2 else ("bearish" if pcr < 0.8 else "neutral")

        # OI buildup (handbook §8): per-leg price x OI change, plus a CE-vs-PE OI-delta
        # read. Put writing (PE OI building) supports; call writing (CE OI building) caps.
        matrix = fno_cfg.get("oi_buildup")
        ce_pc, ce_oc = await _price_oi_change(ce["instrument_token"])
        pe_pc, pe_oc = await _price_oi_change(pe["instrument_token"])
        ce_buildup = classify_buildup(ce_pc, ce_oc, matrix)
        pe_buildup = classify_buildup(pe_pc, pe_oc, matrix)
        if pe_oc - ce_oc > 0:
            oi_bias = "bullish"
        elif ce_oc - pe_oc > 0:
            oi_bias = "bearish"
        else:
            oi_bias = "neutral"
        oi_signal = oi_bias if oi_bias != "neutral" else pcr_signal

        is_banned = name in set(fno_cfg.get("ban_list") or [])

        # Vol direction (5d ATM IV momentum) for the credit-selling spike guard.
        # Best-effort: 0.0 without enough iv_history — the gate then passes.
        try:
            iv_chg_5d = await iv_change_for(name)
        except Exception:
            iv_chg_5d = 0.0

        # Expiry-day flag: TODAY is an expiry date for this underlying (any series) —
        # the pipeline blocks new structures in that pinning regime. NOTE: must check
        # exact membership; nearest_expiry(0,0) returns the NEAREST listing and made
        # every day look like expiry day (Jun-12: 1,974 structures wrongly blocked).
        try:
            from data.option_chain import list_expiries
            is_expiry_day = today_ist() in set(await list_expiries(name))
        except Exception:
            is_expiry_day = False

        return FnoContext(
            spot=spot, iv=round(iv, 4), iv_rank=round(ivr, 1), dte=dte, direction=direction,
            lot_size=int(ce["lot_size"]), expiry=expiry, is_banned=is_banned, strike_step=step,
            oi_signal=oi_signal, risk_free=risk_free, iv_chg_5d=round(iv_chg_5d, 1),
            is_expiry_day=is_expiry_day,
            extra={"atm": atm, "pcr": round(pcr, 2), "pcr_signal": pcr_signal,
                   "oi_bias": oi_bias, "ce_buildup": ce_buildup, "pe_buildup": pe_buildup,
                   "ce_token": ce["instrument_token"], "pe_token": pe["instrument_token"]},
        )
    except Exception as exc:
        log.warning("build_fno_context_failed", name=name, error=str(exc))
        return None
