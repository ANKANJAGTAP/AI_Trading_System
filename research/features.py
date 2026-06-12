"""Rich feature extraction for the meta-labeler (Phase 4).

The discrimination report proved gate SCORES are useless predictors — every traded
signal passed every gate, so the scores are constant among survivors. The *continuous*
context values, by contrast, vary between winners and losers: RVOL magnitude, ADX,
IV-rank, gap %, distance-to-VWAP, DTE, PCR, time-of-day. This module pulls those raw
values into a flat feature dict, captured on every signal (live) and every backtest
trade, so discrimination/training has something that actually varies to learn from.
"""
from __future__ import annotations

from common.market_time import now_ist


def _f(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def extract_features(sleeve: str, ctx, confidence: float, ts=None, signal=None) -> dict:
    """Flat continuous feature vector from a pipeline context (+ the signal for
    trade-quality features). `ts` = decision time (bar in backtest, now in live)."""
    t = ts or now_ist()
    f: dict = {
        "confidence": _f(confidence),
        "hour": float(getattr(t, "hour", 0)),
        "weekday": float(getattr(t, "weekday", lambda: 0)() if callable(getattr(t, "weekday", None)) else 0),
    }
    if sleeve in ("intraday_stocks", "mcx_commodities"):
        vwap = _f(getattr(ctx, "vwap", 0))
        lp = _f(getattr(ctx, "last_price", 0))
        orh, orl = _f(getattr(ctx, "or_high", 0)), _f(getattr(ctx, "or_low", 0))
        regime = getattr(ctx, "regime", None)
        f.update({
            "rvol": _f(getattr(ctx, "rvol", 0)),
            "gap_pct": _f(getattr(ctx, "gap_pct", 0)),
            "vwap_dist_pct": (lp - vwap) / vwap * 100.0 if vwap else 0.0,
            "macd_hist": _f(getattr(ctx, "macd_hist", 0)),
            "st_dir": _f(getattr(ctx, "st_dir", 0)),
            "spread_pct": _f(getattr(ctx, "spread_pct", 0)),
            "or_range_pct": (orh - orl) / lp * 100.0 if lp else 0.0,
            "atr_pct": _f(getattr(ctx, "atr_pct", 0)),            # normalised volatility (#6)
            "rel_strength": _f(getattr(ctx, "rel_strength", 0)),  # leadership vs index (#5)
            "regime_up": 1.0 if regime == "trending_up" else 0.0,
            "regime_down": 1.0 if regime == "trending_down" else 0.0,
            "breadth_bull": 1.0 if getattr(ctx, "day_breadth", "") == "bullish" else 0.0,
            "breadth_bear": 1.0 if getattr(ctx, "day_breadth", "") == "bearish" else 0.0,
        })
        if signal is not None:   # trade-quality (#9, #10)
            entry, stop, target = _f(getattr(signal, "entry", 0)), _f(getattr(signal, "stop", 0)), _f(getattr(signal, "target", 0))
            risk = abs(entry - stop)
            f["stop_pct"] = risk / entry * 100.0 if entry else 0.0
            f["reward_risk"] = abs(target - entry) / risk if risk else 0.0
    elif sleeve == "swing_stocks":
        lp = _f(getattr(ctx, "last_price", 0))
        s200 = _f(getattr(ctx, "sma200", 0))
        atr = _f(getattr(ctx, "atr", 0))
        f.update({
            "dist_200dma_pct": (lp - s200) / s200 * 100.0 if s200 else 0.0,
            "atr_pct": atr / lp * 100.0 if lp else 0.0,
            "rel_strength": _f(getattr(ctx, "rel_strength", 0)),
            "market_uptrend": 1.0 if getattr(ctx, "market_uptrend", False) else 0.0,
        })
        if signal is not None:
            entry, stop, target = _f(getattr(signal, "entry", 0)), _f(getattr(signal, "stop", 0)), _f(getattr(signal, "target", 0))
            risk = abs(entry - stop)
            f["stop_pct"] = risk / entry * 100.0 if entry else 0.0
            f["reward_risk"] = abs(target - entry) / risk if risk else 0.0
    elif sleeve == "fno":
        extra = getattr(ctx, "extra", {}) or {}
        direction = getattr(ctx, "direction", None)
        spot, step, lot = _f(getattr(ctx, "spot", 0)), _f(getattr(ctx, "strike_step", 0)), _f(getattr(ctx, "lot_size", 0))
        f.update({
            "iv": _f(getattr(ctx, "iv", 0)),
            "iv_rank": _f(getattr(ctx, "iv_rank", 0)),
            "iv_chg_5d": _f(getattr(ctx, "iv_chg_5d", 0)),   # vol momentum at entry
            "dte": _f(getattr(ctx, "dte", 0)),
            "pcr": _f(extra.get("pcr", 1.0)),
            "strike_step": step,
            "dir_bull": 1.0 if direction == "bullish" else 0.0,
            "dir_bear": 1.0 if direction == "bearish" else 0.0,
        })
        struct = (getattr(signal, "detail", {}) or {}).get("structure", {}) if signal is not None else {}
        stype = str(struct.get("type", ""))
        short_leg = _f(struct.get("short_leg", 0))
        long_leg = _f(struct.get("long_leg", 0))
        mll = _f(struct.get("max_loss_per_lot", 0))
        width = abs(short_leg - long_leg)
        if stype:
            f["is_condor"] = 1.0 if stype == "iron_condor" else 0.0
            f["is_credit"] = 1.0 if ("credit" in stype or stype == "iron_condor") else 0.0
        if short_leg and spot:   # short-strike moneyness % (#11)
            f["moneyness_pct"] = (short_leg - spot) / spot * 100.0
        cr = _f(struct.get("net_credit", 0))
        if cr > 0 and long_leg > 0 and width > 0:   # premium richness per unit width
            f["credit_ratio"] = cr / width
        if mll > 0 and lot and long_leg > 0 and width > 0:   # WIDTH-aware reward:risk (#12)
            f["reward_risk"] = max(0.0, width * lot - mll) / mll
        elif mll > 0 and step and lot:   # legacy rows without a long leg recorded
            f["reward_risk"] = max(0.0, step * lot - mll) / mll
    return f


def gate_features(gates) -> dict:
    """Gate scores as `gate_<name>` features (kept for completeness — discrimination
    will show they don't vary, which is the point)."""
    out: dict = {}
    for g in gates or []:
        name = getattr(g, "name", None) if hasattr(g, "name") else g.get("name")
        score = float(getattr(g, "score", 0) or 0) if hasattr(g, "score") else float(g.get("score", 0) or 0)
        if name:
            out[f"gate_{name}"] = score
    return out


def signal_features(sleeve: str, ctx, confidence: float, gates, ts=None, signal=None) -> dict:
    """The full feature dict stored per signal/trade: rich context + gate scores."""
    return {**extract_features(sleeve, ctx, confidence, ts, signal), **gate_features(gates)}
