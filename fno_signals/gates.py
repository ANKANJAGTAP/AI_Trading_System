"""
Hard gates — deterministic checks that can only REJECT a signal, never create
one. A signal that fails any hard gate is dropped before sizing. (Soft scoring
lives in the meta-label step.) Every check is recorded in a trail for audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class GateConfig:
    min_atm_oi: int = 5_000
    min_atm_volume: int = 100
    max_spread_pct: float = 5.0      # only applied if bid/ask present
    min_dte: int = 1
    max_dte: int = 45


@dataclass
class GateResult:
    passed: bool
    trail: list = field(default_factory=list)   # (gate, passed, detail)

    @property
    def reject_reason(self):
        for name, ok, detail in self.trail:
            if not ok:
                return f"{name}: {detail}"
        return None


def _atm_row(chain, spot, opt_type):
    sub = chain[chain["opt_type"] == opt_type]
    if sub.empty:
        return None
    i = (sub["strike"] - spot).abs().idxmin()
    return sub.loc[i]


def run_hard_gates(ctx, cfg: GateConfig = GateConfig()) -> GateResult:
    trail = []

    chain_ok = ctx.chain is not None and not ctx.chain.empty
    trail.append(("chain_present", chain_ok, "" if chain_ok else "empty chain"))
    if not chain_ok:
        return GateResult(False, trail)

    # liquidity at ATM (both CE and PE)
    ce, pe = _atm_row(ctx.chain, ctx.spot, "CE"), _atm_row(ctx.chain, ctx.spot, "PE")
    oi = min(ce["oi"] if ce is not None else 0, pe["oi"] if pe is not None else 0)
    vol = min(ce["volume"] if ce is not None else 0, pe["volume"] if pe is not None else 0)
    liq_ok = oi >= cfg.min_atm_oi and vol >= cfg.min_atm_volume
    trail.append(("liquidity", bool(liq_ok), f"atm_oi={int(oi)} atm_vol={int(vol)}"))

    # spread (only if quotes available)
    if {"bid", "ask"}.issubset(ctx.chain.columns) and ce is not None:
        mid = (ce["bid"] + ce["ask"]) / 2
        spread_pct = (ce["ask"] - ce["bid"]) / mid * 100 if mid > 0 else np.inf
        sp_ok = spread_pct <= cfg.max_spread_pct
        trail.append(("spread", bool(sp_ok), f"{spread_pct:.2f}%"))

    # days to expiry window
    dte_ok = cfg.min_dte <= ctx.dte <= cfg.max_dte
    trail.append(("dte_window", bool(dte_ok), f"dte={ctx.dte}"))

    # event blackout
    ev_ok = ctx.timestamp.normalize() not in set(pd.Timestamp(e).normalize() for e in ctx.events) \
        if ctx.events else True
    trail.append(("event_blackout", bool(ev_ok), "blackout" if not ev_ok else ""))

    passed = all(ok for _, ok, _ in trail)
    return GateResult(passed, trail)
