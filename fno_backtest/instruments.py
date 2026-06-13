"""
Option legs and multi-leg structures with cash-settled expiry payoffs.

Index F&O in India is cash-settled, so a structure's expiry P&L is the sum of
each leg's (intrinsic - entry) for longs and (entry - intrinsic) for shorts.
A Structure is tracked as one defined-risk position (the F&O sleeve never sells
naked), with max-loss / max-profit / breakevens derived by scanning spot.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def intrinsic(opt_type: str, strike: float, spot: float) -> float:
    if opt_type == "CE":
        return max(spot - strike, 0.0)
    if opt_type == "PE":
        return max(strike - spot, 0.0)
    if opt_type == "FUT":
        return spot
    raise ValueError(f"bad opt_type {opt_type!r}")


@dataclass
class Leg:
    opt_type: str           # 'CE' | 'PE' | 'FUT'
    strike: float           # 0.0 for futures
    side: str               # 'BUY' | 'SELL'
    qty: int                # units (lots * lot_size)
    entry_price: float = 0.0

    @property
    def segment(self) -> str:
        return "FUT" if self.opt_type == "FUT" else "OPT"

    def payoff(self, spot: float) -> float:
        val = intrinsic(self.opt_type, self.strike, spot)
        per_unit = (val - self.entry_price) if self.side.upper() == "BUY" \
            else (self.entry_price - val)
        return per_unit * self.qty


@dataclass
class Structure:
    name: str
    legs: list[Leg] = field(default_factory=list)

    def payoff_at(self, spot: float) -> float:
        return sum(leg.payoff(spot) for leg in self.legs)

    def net_premium(self) -> float:
        """>0 = net debit paid; <0 = net credit received (options only)."""
        prem = 0.0
        for leg in self.legs:
            if leg.opt_type == "FUT":
                continue
            prem += leg.entry_price * leg.qty * (1 if leg.side.upper() == "BUY" else -1)
        return prem

    def profile(self, spot_lo: float, spot_hi: float, n: int = 600) -> dict:
        spots = np.linspace(spot_lo, spot_hi, n)
        pay = np.array([self.payoff_at(s) for s in spots])
        # breakevens = sign changes
        sign = np.sign(pay)
        be = [float((spots[i] + spots[i + 1]) / 2)
              for i in range(len(spots) - 1) if sign[i] != sign[i + 1] and sign[i] != 0]
        return {
            "max_profit": float(pay.max()),
            "max_loss": float(pay.min()),
            "breakevens": be,
        }


def settlement_pnl(structure: Structure, settle_spot: float) -> float:
    """Realised P&L if the structure is held to expiry and cash-settled."""
    return structure.payoff_at(settle_spot)


# ---- common defined-risk builders ------------------------------------- #
def bull_call_spread(k_lo, k_hi, qty, price_lo, price_hi) -> Structure:
    return Structure("bull_call_debit", [
        Leg("CE", k_lo, "BUY", qty, price_lo),
        Leg("CE", k_hi, "SELL", qty, price_hi),
    ])


def bear_put_spread(k_hi, k_lo, qty, price_hi, price_lo) -> Structure:
    return Structure("bear_put_debit", [
        Leg("PE", k_hi, "BUY", qty, price_hi),
        Leg("PE", k_lo, "SELL", qty, price_lo),
    ])


def iron_condor(put_long, put_short, call_short, call_long, qty,
                p_pl, p_ps, p_cs, p_cl) -> Structure:
    return Structure("iron_condor", [
        Leg("PE", put_long, "BUY", qty, p_pl),
        Leg("PE", put_short, "SELL", qty, p_ps),
        Leg("CE", call_short, "SELL", qty, p_cs),
        Leg("CE", call_long, "BUY", qty, p_cl),
    ])
