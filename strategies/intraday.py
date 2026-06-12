"""Intraday Stocks pipeline (spec §5.1). Funnel: liquidity -> regime -> time window
-> ORB / VWAP-pullback setup -> confirmation (VWAP side + RVOL) -> signal. The core
`evaluate_intraday` is reused by the MCX intraday pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from strategies.base import GateRunner, PipelineResult, Signal


@dataclass
class IntradayContext:
    last_price: float
    or_high: float                 # opening-range high (9:15-9:30)
    or_low: float
    vwap: float
    rvol: float                    # relative volume
    daily_adv: float               # avg daily volume (shares)
    spread_pct: float              # current bid-ask spread %
    gap_pct: float                 # today's gap vs prev close
    regime: str                    # trending_up | trending_down | choppy
    sector_strong: bool = True
    now_window_ok: bool = True     # within entry window & before last-entry
    macd_hist: float = 0.0         # MACD histogram (momentum confirmation)
    st_dir: int = 0                # SuperTrend direction (+1 up, -1 down, 0 unknown)
    atr_pct: float = 0.0           # daily ATR as % of price (normalised volatility)
    rel_strength: float = 0.0      # 20d return minus index 20d return (leadership)
    day_breadth: str = "unknown"   # live day-type: bullish | bearish | mixed | unknown
                                   # (% of universe above VWAP, computed by the engine)
    extra: dict = field(default_factory=dict)


def evaluate_intraday(instrument: dict, ctx: IntradayContext, params: dict,
                      sleeve: str, require_sector: bool = True) -> PipelineResult:
    g = GateRunner()
    uni = params.get("universe", {})
    rvolp = params.get("rvol", {})

    # 1. liquidity
    min_adv = uni.get("min_avg_daily_volume", 500000)
    pref = (uni.get("preferred_avg_daily_volume") or [2000000])[0]
    liq_ok = ctx.daily_adv >= min_adv and ctx.spread_pct <= uni.get("max_bid_ask_spread_pct", 0.10)
    if not g.add("liquidity", liq_ok, min(1.0, ctx.daily_adv / pref),
                 adv=ctx.daily_adv, spread_pct=ctx.spread_pct):
        return g.reject("illiquid (ADV/spread)")

    # 2. time window
    if not g.add("time_window", ctx.now_window_ok, 1.0 if ctx.now_window_ok else 0.0):
        return g.reject("outside entry window / past last-entry")

    # 3. regime (choppy disables breakouts)
    trending = ctx.regime in ("trending_up", "trending_down")
    if not g.add("regime", trending, 1.0 if trending else 0.0, regime=ctx.regime):
        return g.reject("choppy regime (breakouts disabled)")

    # 4. setup: ORB then VWAP-pullback. Freshness filter: a 60s polling loop sees
    # "price > OR-high" ALL DAY — only take the breakout while price is still near
    # the trigger (within max_extension_pct), not a late chase of an extended move
    # with the stop all the way back at the other side of the range.
    orbp = params.get("orb", {})
    max_ext = float(orbp.get("max_extension_pct", 0.3))
    side = setup = None
    entry = ctx.last_price
    stop = None
    if ctx.last_price > ctx.or_high and ctx.regime == "trending_up":
        if ctx.or_high > 0 and (ctx.last_price - ctx.or_high) / ctx.or_high * 100.0 <= max_ext:
            side, setup, stop = "BUY", "orb", ctx.or_low
    elif ctx.last_price < ctx.or_low and ctx.regime == "trending_down":
        if ctx.or_low > 0 and (ctx.or_low - ctx.last_price) / ctx.or_low * 100.0 <= max_ext:
            side, setup, stop = "SELL", "orb", ctx.or_high
    if side is None:
        near_vwap = ctx.vwap > 0 and abs(ctx.last_price - ctx.vwap) / ctx.vwap <= 0.003
        if near_vwap and ctx.regime == "trending_up" and ctx.last_price >= ctx.vwap:
            side, setup, stop = "BUY", "vwap_pullback", round(ctx.vwap * 0.997, 2)
        elif near_vwap and ctx.regime == "trending_down" and ctx.last_price <= ctx.vwap:
            side, setup, stop = "SELL", "vwap_pullback", round(ctx.vwap * 1.003, 2)
    if not g.add("setup", side is not None, 1.0 if side else 0.0, setup=setup):
        return g.reject("no ORB / VWAP-pullback setup (or breakout too extended)")

    # 4a. breadth day-type gate ("when it trades matters more than how"): longs need a
    # bullish day (most of the universe above VWAP), shorts a bearish one. A mixed day
    # is a chop day — ORB's worst regime — so no entries at all. Unknown fails OPEN.
    bg = params.get("breadth_gate", {}) or {}
    if bg.get("enabled", False) and ctx.day_breadth in ("bullish", "bearish", "mixed"):
        b_ok = (side == "BUY" and ctx.day_breadth == "bullish") or \
               (side == "SELL" and ctx.day_breadth == "bearish")
        if not g.add("breadth", b_ok, 0.9 if b_ok else 0.0, day_breadth=ctx.day_breadth):
            return g.reject(f"day breadth '{ctx.day_breadth}' does not support {side} entries")

    # 4b. stop-distance sanity: a stop further than max_stop_distance_pct of price
    # (e.g. a very wide opening range) makes the 1.5R target unrealistic intraday
    # and the position size negligible after clamps — skip rather than chase.
    max_stop_pct = float(orbp.get("max_stop_distance_pct", 1.5))
    stop_pct = abs(entry - stop) / entry * 100.0 if entry > 0 else 999.0
    if not g.add("stop_distance", stop_pct <= max_stop_pct,
                 max(0.0, 1.0 - stop_pct / max(max_stop_pct, 0.01)), stop_pct=round(stop_pct, 2)):
        return g.reject(f"stop {stop_pct:.1f}% of price too wide (> {max_stop_pct}%)")

    # 5. confirmation: correct VWAP side + RVOL
    on_side = (side == "BUY" and ctx.last_price >= ctx.vwap) or (side == "SELL" and ctx.last_price <= ctx.vwap)
    rvol_min = rvolp.get("orb_min", 1.5) if setup == "orb" else rvolp.get("vwap_pullback_min", 1.2)
    rvol_ideal = rvolp.get("orb_ideal", 2.0)
    conf_ok = on_side and ctx.rvol >= rvol_min
    if not g.add("confirmation", conf_ok, min(1.0, ctx.rvol / rvol_ideal), rvol=ctx.rvol, on_vwap_side=on_side):
        return g.reject("confirmation failed (VWAP side / RVOL)")

    # 6. momentum confirmation (MACD histogram + SuperTrend agree with the side).
    # Non-rejecting on purpose: it tunes CONFIDENCE (size within R), it does not block
    # a setup the funnel already accepts — added without backtest-proven thresholds.
    if side == "BUY":
        mom_ok = ctx.macd_hist > 0 and ctx.st_dir >= 0
    else:
        mom_ok = ctx.macd_hist < 0 and ctx.st_dir <= 0
    g.add("momentum", True, 0.85 if mom_ok else 0.4,
          macd_hist=round(ctx.macd_hist, 4), st_dir=ctx.st_dir, confirms=mom_ok)

    # 7. soft filters (gap / sector) -> contribute to confidence
    gap_up = ctx.gap_pct >= params.get("gap", {}).get("threshold_pct", 0.5)
    sector_ok = ctx.sector_strong or not require_sector
    g.add("filters", sector_ok, 0.5 + 0.25 * gap_up + 0.25 * bool(ctx.sector_strong),
          gap_up=gap_up, sector_strong=ctx.sector_strong)
    if require_sector and not ctx.sector_strong:
        return g.reject("sector not strong")

    # signal: reward leg from config (min 1.5R)
    reward = (params.get("reward_R") or [1.5])[0]
    risk = abs(entry - stop)
    target = round(entry + reward * risk, 2) if side == "BUY" else round(entry - reward * risk, 2)
    return g.accept(Signal(sleeve, instrument, side, setup, round(entry, 2), round(stop, 2), target,
                           {"reward_R": reward, "risk_per_unit": round(risk, 2)}))


class IntradayPipeline:
    sleeve = "intraday_stocks"

    def __init__(self, config) -> None:
        self.params = config.strategy.intraday_stocks

    async def evaluate(self, instrument: dict, ctx: IntradayContext) -> PipelineResult:
        return evaluate_intraday(instrument, ctx, self.params, self.sleeve, require_sector=True)
