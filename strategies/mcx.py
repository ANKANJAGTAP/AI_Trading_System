"""MCX Commodities pipeline (spec §5.4). Reuses the intraday + swing gate logic,
adapted to commodities: extended session (caller sets now_window_ok from the MCX
calendar ~09:00-23:30 IST), no equity sector filter, and swing trend-following
with the fundamental filter disabled (macro/inventory context is LLM-only, Phase 5).
"""
from __future__ import annotations

from strategies.intraday import IntradayContext, evaluate_intraday
from strategies.swing import SwingContext, SwingPipeline
from strategies.base import PipelineResult


class McxIntradayPipeline:
    sleeve = "mcx_commodities"

    def __init__(self, config) -> None:
        # Reuse the intraday gate thresholds (RVOL/reward/gap); commodities have no sector.
        self.params = config.strategy.intraday_stocks
        self.session = (config.strategy.mcx_commodities or {}).get("session", {})

    async def evaluate(self, instrument: dict, ctx: IntradayContext) -> PipelineResult:
        return evaluate_intraday(instrument, ctx, self.params, self.sleeve, require_sector=False)


class McxSwingPipeline:
    sleeve = "mcx_commodities"

    def __init__(self, config) -> None:
        self._swing = SwingPipeline(config, sleeve="mcx_commodities")

    async def evaluate(self, instrument: dict, ctx: SwingContext) -> PipelineResult:
        ctx.fundamentals_required = False   # commodities: no fundamental filter
        return await self._swing.evaluate(instrument, ctx)
