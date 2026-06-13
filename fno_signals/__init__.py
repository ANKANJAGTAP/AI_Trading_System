"""
fno_signals — Pillar 5 of the world-class F&O platform.

The strategy/signal engine: the 7-step decision pipeline that turns market
context into defined-risk trade decisions for index options, integrating the
data, feature, ML-validation and backtest pillars.

  context     : MarketContext (point-in-time decision snapshot)
  signal      : rule-based primary directional/vol view
  gates       : hard gates (liquidity / spread / DTE / event)
  regime      : IV-regime -> structure-family routing
  structures  : build a defined-risk Structure from the chain
  sizing      : R-based, confidence-scaled position sizing
  risk        : kill-switch, portfolio-R, options-aware scenario gate
  pipeline    : decide() -> TradeDecision (the capstone)
"""
from . import context, signal, gates, regime, structures, sizing, risk, pipeline, execution  # noqa: F401
from .context import MarketContext
from .execution import to_kite_orders, place_orders
from .signal import Signal, generate_signal
from .gates import GateConfig, run_hard_gates
from .regime import iv_regime, route
from .structures import select_structure, one_lot_max_loss
from .sizing import SizingConfig, effective_R, size_lots
from .risk import RiskState, scenario_loss_ok
from .pipeline import DecisionConfig, TradeDecision, decide

__version__ = "0.1.0"
__all__ = [
    "context", "signal", "gates", "regime", "structures", "sizing", "risk", "pipeline", "execution",
    "MarketContext", "Signal", "generate_signal",
    "to_kite_orders", "place_orders",
    "GateConfig", "run_hard_gates", "iv_regime", "route",
    "select_structure", "one_lot_max_loss",
    "SizingConfig", "effective_R", "size_lots",
    "RiskState", "scenario_loss_ok",
    "DecisionConfig", "TradeDecision", "decide",
]
