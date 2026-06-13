"""
fno_backtest — Pillar 4 of the world-class F&O platform.

An options-aware, cost-realistic, bias-resistant backtester for defined-risk
index-option structures, wired to the Pillar-3 validation gates.

  costs       : Indian F&O statutory cost model (CostConfig)
  fills       : OHLC best/mid/worst + order-book VWAP fills
  instruments : Leg / Structure, cash-settled expiry payoff, builders
  engine      : simulate_trade + EventDrivenBacktester + backtest_strategy
  report      : canonical report (+ bias-audit header), reuses ml.metrics
  analysis    : Monte-Carlo trade-bootstrap + spot x IV scenario grid
"""
from . import costs, fills, instruments, engine, report, analysis  # noqa: F401
from .costs import CostConfig, leg_cost, round_trip_cost
from .fills import ohlc_fill, book_vwap_fill
from .instruments import (
    Leg, Structure, intrinsic, settlement_pnl,
    bull_call_spread, bear_put_spread, iron_condor,
)
from .engine import simulate_trade, EventDrivenBacktester, BacktestResult, backtest_strategy
from .analysis import monte_carlo_paths, scenario_grid

__version__ = "0.1.0"
__all__ = [
    "costs", "fills", "instruments", "engine", "report", "analysis",
    "CostConfig", "leg_cost", "round_trip_cost",
    "ohlc_fill", "book_vwap_fill",
    "Leg", "Structure", "intrinsic", "settlement_pnl",
    "bull_call_spread", "bear_put_spread", "iron_condor",
    "simulate_trade", "EventDrivenBacktester", "BacktestResult", "backtest_strategy",
    "monte_carlo_paths", "scenario_grid",
]
