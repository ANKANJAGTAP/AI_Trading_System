"""Swing Stocks pipeline (spec §5.3). Funnel: fundamentals (junk removal) ->
price>200DMA -> market regime -> sector strength -> technical setup -> event gate
-> signal (ATR/swing-low stop). Reused for MCX swing with fundamentals disabled.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from strategies.base import GateRunner, PipelineResult, Signal


@dataclass
class SwingContext:
    last_price: float
    sma200: float                  # split/bonus-adjusted 200 DMA
    atr: float
    market_uptrend: bool
    sector_strong: bool
    setup_ok: bool                 # pullback-to-support OR base breakout + volume
    setup: str = "swing"
    event_in_window: bool = False  # earnings/major event in holding window
    fundamentals: dict = field(default_factory=dict)
    fundamentals_required: bool = True


class SwingPipeline:
    def __init__(self, config, sleeve: str = "swing_stocks") -> None:
        self.p = config.strategy.swing_stocks
        self.sleeve = sleeve

    async def evaluate(self, instrument: dict, ctx: SwingContext) -> PipelineResult:
        g = GateRunner()
        p = self.p

        # 1. fundamentals (junk removal)
        if ctx.fundamentals_required:
            f = ctx.fundamentals or {}
            fp = p.get("fundamentals", {})
            checks = {
                "market_cap": float(f.get("market_cap_cr", 0)) >= fp.get("market_cap_min_cr", 5000),
                "roe": float(f.get("roe", 0)) >= fp.get("roe_min_pct", 15),
                "rev_growth": float(f.get("revenue_growth", 0)) >= fp.get("revenue_growth_min_pct", 10),
                "eps_growth": float(f.get("eps_growth", 0)) >= fp.get("eps_growth_min_pct", 15),
                "debt_equity": float(f.get("debt_equity", 99)) <= fp.get("debt_equity_max", 0.5),
                "promoter": str(f.get("promoter_holding_trend", "")) in ("stable", "rising", "stable_or_rising"),
                "adv": float(f.get("avg_daily_volume", 0)) >= fp.get("avg_daily_volume_min", 1000000),
            }
            n_ok = sum(checks.values())
            if not g.add("fundamentals", all(checks.values()), n_ok / len(checks), checks=checks):
                return g.reject(f"fundamentals fail ({n_ok}/{len(checks)})")
        else:
            g.add("fundamentals", True, 1.0, skipped=True)

        # 2. price above 200 DMA
        above = ctx.last_price > ctx.sma200 > 0
        if not g.add("above_200dma", above, 1.0 if above else 0.0,
                     price=ctx.last_price, sma200=round(ctx.sma200, 2)):
            return g.reject("price below 200 DMA")

        # 3. broad market regime
        if p.get("regime", {}).get("require_market_uptrend", True):
            if not g.add("market_regime", ctx.market_uptrend, 1.0 if ctx.market_uptrend else 0.0):
                return g.reject("broad market not in uptrend")
        else:
            g.add("market_regime", True, 1.0)

        # 4. sector strength
        if not g.add("sector_strength", ctx.sector_strong, 1.0 if ctx.sector_strong else 0.4):
            return g.reject("sector not outperforming")

        # 5. technical setup
        if not g.add("technical_setup", ctx.setup_ok, 0.9 if ctx.setup_ok else 0.0, setup=ctx.setup):
            return g.reject("no valid pullback/breakout setup")

        # 6. event gate (default reduce-or-skip)
        action = p.get("event_gate", {}).get("on_event_in_holding_window", "reduce_or_skip")
        if ctx.event_in_window and action == "reduce_or_skip":
            if not g.add("event_gate", False, 0.0, event_in_window=True):
                return g.reject("earnings/major event within holding window")
        else:
            g.add("event_gate", True, 1.0, event_in_window=ctx.event_in_window)

        # signal: wide ATR-based stop (long swing), target 2R
        atr_mult = p.get("stops", {}).get("atr_multiple", 2.0)
        stop = round(ctx.last_price - atr_mult * ctx.atr, 2)
        risk = ctx.last_price - stop
        target = round(ctx.last_price + 2 * risk, 2)
        sig = Signal(self.sleeve, instrument, "BUY", ctx.setup or "swing",
                     round(ctx.last_price, 2), stop, target,
                     {"atr": round(ctx.atr, 2),
                      "holding_horizon_days": p.get("holding_horizon", {}).get("target_days", [5, 20])})
        return g.accept(sig)
