"""
The 7-step F&O decision pipeline — the capstone that turns market context into a
defined-risk trade decision, wiring together all five pillars:

  context (P1 data + P2 features) -> [1] signal -> [2] hard gates ->
  [3] meta-label filter (P3) -> [4] structure selection (regime route) ->
  [5] R-sizing -> [6] pre-trade risk + scenario gate (P4) -> [7] execution intent.

`decide()` is pure and deterministic given its inputs, returning a TradeDecision
with a full audit trail whether accepted or rejected.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fno_backtest.instruments import Leg, Structure
from ml.models import size_multiplier

from .signal import generate_signal, Signal
from .gates import run_hard_gates, GateConfig
from .regime import iv_regime, route
from .structures import select_structure, one_lot_max_loss
from .sizing import SizingConfig, effective_R, size_lots
from .risk import RiskState, scenario_loss_ok


@dataclass
class DecisionConfig:
    sizing: SizingConfig
    gate: GateConfig = field(default_factory=GateConfig)
    width_steps: int = 2
    wing_steps: int = 2
    veto_below: float = 0.40
    neutral_above: float = 0.60
    scenario_loss_buffer: float = 2.0     # allow worst-case MTM up to N x expiry max-loss


@dataclass
class TradeDecision:
    underlying: str
    timestamp: object
    accepted: bool
    reject_reason: str | None = None
    signal: Signal | None = None
    family: str | None = None
    structure: Structure | None = None
    lots: int = 0
    qty: int = 0
    max_loss: float = 0.0
    confidence: float = 0.0
    sized_R: float = 0.0
    gate_trail: list = field(default_factory=list)


def _scale(structure: Structure, lots: int) -> Structure:
    return Structure(structure.name, [
        Leg(l.opt_type, l.strike, l.side, l.qty * lots, l.entry_price)
        for l in structure.legs
    ])


def decide(ctx, cfg: DecisionConfig, risk_state: RiskState,
           meta_confidence: float | None = None, iv_spiking: bool = False) -> TradeDecision:
    def reject(reason, **kw):
        return TradeDecision(ctx.underlying, ctx.timestamp, False, reason, **kw)

    # [1] primary signal
    sig = generate_signal(ctx)

    # [2] hard gates
    gr = run_hard_gates(ctx, cfg.gate)
    if not gr.passed:
        return reject(gr.reject_reason, signal=sig, gate_trail=gr.trail)

    # [3] meta-label filter (veto / shrink, never inflate)
    p = sig.view_strength if meta_confidence is None else float(meta_confidence)
    mult = size_multiplier(p, cfg.veto_below, cfg.neutral_above)
    if mult <= 0:
        return reject(f"meta-veto (p={p:.2f})", signal=sig, confidence=p, gate_trail=gr.trail)

    # [4] structure selection via IV-regime routing
    family = route(sig.direction, iv_regime(ctx.iv_rank), iv_spiking)
    if family is None:
        return reject("route blocked (e.g. credit-sell into IV spike)",
                      signal=sig, confidence=p, gate_trail=gr.trail)
    structure = select_structure(family, ctx.chain, ctx.spot, ctx.lot_size,
                                 ctx.step, cfg.width_steps, cfg.wing_steps)
    if structure is None:
        return reject(f"{family}: strikes/prices unavailable",
                      signal=sig, family=family, confidence=p, gate_trail=gr.trail)
    max_loss_1lot = one_lot_max_loss(structure, ctx.spot)
    if max_loss_1lot <= 0:
        return reject(f"{family}: non-finite/zero max loss",
                      signal=sig, family=family, confidence=p, gate_trail=gr.trail)

    # [5] R-based sizing (confidence * meta multiplier)
    eff_R = effective_R(cfg.sizing, p * mult)
    lots = size_lots(eff_R, max_loss_1lot, cfg.sizing, risk_state.portfolio_remaining_R())
    if lots < 1:
        return reject("size < 1 lot for R budget", signal=sig, family=family,
                      structure=structure, max_loss=max_loss_1lot, confidence=p,
                      sized_R=eff_R, gate_trail=gr.trail)
    scaled = _scale(structure, lots)
    total_max_loss = max_loss_1lot * lots

    # [6] pre-trade risk
    if risk_state.kill_switch_tripped():
        return reject("daily kill-switch tripped", signal=sig, family=family,
                      structure=scaled, confidence=p, gate_trail=gr.trail)
    if not risk_state.can_add_position():
        return reject("max concurrent positions", signal=sig, family=family,
                      structure=scaled, confidence=p, gate_trail=gr.trail)
    ok, worst = scenario_loss_ok(scaled, ctx.spot, ctx.t_years(), ctx.atm_iv,
                                 max_loss_limit=total_max_loss * cfg.scenario_loss_buffer)
    if not ok:
        return reject(f"scenario worst-case {worst:.0f} exceeds limit",
                      signal=sig, family=family, structure=scaled,
                      max_loss=total_max_loss, confidence=p, gate_trail=gr.trail)

    # [7] accepted -> execution intent is the scaled, defined-risk structure
    return TradeDecision(
        ctx.underlying, ctx.timestamp, True, None,
        signal=sig, family=family, structure=scaled, lots=lots,
        qty=ctx.lot_size * lots, max_loss=total_max_loss,
        confidence=p, sized_R=eff_R, gate_trail=gr.trail,
    )
