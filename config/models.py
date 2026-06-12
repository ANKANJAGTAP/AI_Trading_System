"""Typed models for the YAML tunables (`config/*.yaml`).

Every parameter from the build spec is represented here so it is validated on
load and tunable without code changes. Sections that will be deepened in later
phases (strategy thresholds, cost model) use `extra="allow"` so new keys can be
added to the YAML without breaking config loading.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RangeDefault(BaseModel):
    """A parameter with an operator-tunable range and a default."""

    min: float | None = None
    max: float | None = None
    default: float


class Leverage(BaseModel):
    model_config = ConfigDict(extra="allow")
    mode: str = "only_when_needed"
    target_effective_exposure: list[float] = [1.5, 3.0]


class RiskConfig(BaseModel):
    """Section 4 — Core Risk Model."""

    model_config = ConfigDict(extra="allow")
    per_trade_risk_pct: RangeDefault
    daily_max_loss_pct: RangeDefault
    portfolio_risk_limit_pct: RangeDefault
    leverage: Leverage
    per_instrument_cap_pct: float
    kill_switch: dict = {}

    @property
    def max_concurrent_positions(self) -> int:
        """Max Positions = Portfolio Risk Limit / Risk Per Trade (spec §4)."""
        per_trade = self.per_trade_risk_pct.default
        if per_trade <= 0:
            return 0
        return int(self.portfolio_risk_limit_pct.default // per_trade)


class SleeveConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    cap_pct: float
    enabled: bool = True
    instruments: str | list[str] | None = None


class SleevesConfig(BaseModel):
    """Section 3 — Capital, Sleeves & Allocation."""

    model_config = ConfigDict(extra="allow")
    sleeves: dict[str, SleeveConfig]


class ExecutionConfig(BaseModel):
    """Section 8 — Execution & Order Management."""

    model_config = ConfigDict(extra="allow")
    mode: str = "simulated_fill"          # simulated_fill (default) | live
    default_order_type: str = "MARKET"
    slippage_bps: float = 2.0
    cost_model: dict = {}
    partial_fill: dict = {}
    rejection: dict = {}
    freeze_quantity: dict = {}
    oco_gtt: dict = {}


class DataConfig(BaseModel):
    """Section 7 — Data Layer (rate limits, candles, feed, universe, backfill)."""

    model_config = ConfigDict(extra="allow")
    rate_limits: dict = {}
    candles: dict = {}
    feed: dict = {}
    universe: dict = {}
    backfill: dict = {}


class SystemConfig(BaseModel):
    """System-level: timezone, sessions, scheduler, LLM, alerts."""

    model_config = ConfigDict(extra="allow")
    timezone: str = "Asia/Kolkata"
    token_refresh_time: str = "08:00"     # IST, before market open
    market: dict = {}
    llm: dict = {}
    alerts: dict = {}
    confidence: dict = {}


class StrategyParams(BaseModel):
    """Section 5 — the four pipelines. Permissive: deepened in Phase 4."""

    model_config = ConfigDict(extra="allow")
    intraday_stocks: dict = {}
    fno: dict = {}
    swing_stocks: dict = {}
    mcx_commodities: dict = {}


class AppConfig(BaseModel):
    """Aggregate of all YAML config, validated on load."""

    risk: RiskConfig
    sleeves: SleevesConfig
    execution: ExecutionConfig
    data: DataConfig
    system: SystemConfig
    strategy: StrategyParams
