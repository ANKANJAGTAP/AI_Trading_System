"""Options-structure analytics for the dashboard Structure Lab (§10 Phase 6) — pure.

Builds the at-expiry payoff curve + the full risk profile (net Greeks, scenario/stress
VaR, SPAN margin, expiry action) for a multi-leg structure, reusing the Black-Scholes
pricer and the Phase 5 risk engines. No I/O — the API route is a thin wrapper.
"""
from __future__ import annotations

from data.options import bs_price
from risk.structure_risk import assess_structure

R = 0.06


def expiry_payoff(legs: list[dict], S: float) -> float:
    """Structure P&L at expiry for underlying price S. legs: {opt, K, qty(signed),
    entry_px(premium per unit)}."""
    total = 0.0
    for leg in legs:
        opt, K, qty = leg.get("opt"), float(leg["K"]), float(leg["qty"])
        prem = float(leg.get("entry_px", 0.0))
        if opt == "CE":
            intrinsic = max(0.0, S - K)
        elif opt == "PE":
            intrinsic = max(0.0, K - S)
        else:
            intrinsic = S - K
        total += qty * (intrinsic - prem)
    return round(total, 2)


def payoff_curve(legs: list[dict], spot: float, *, width_pct: float = 0.15,
                 points: int = 41) -> list[dict]:
    if spot <= 0 or points < 2:
        return []
    lo, hi = spot * (1 - width_pct), spot * (1 + width_pct)
    step = (hi - lo) / (points - 1)
    return [{"spot": round(lo + i * step, 2), "pnl": expiry_payoff(legs, lo + i * step)}
            for i in range(points)]


def _breakevens(curve: list[dict]) -> list[float]:
    """Underlying prices where the payoff crosses zero (linear interpolation)."""
    bes = []
    for a, b in zip(curve, curve[1:]):
        if a["pnl"] == 0:
            bes.append(a["spot"])
        elif a["pnl"] * b["pnl"] < 0:
            frac = -a["pnl"] / (b["pnl"] - a["pnl"])
            bes.append(round(a["spot"] + frac * (b["spot"] - a["spot"]), 2))
    return bes


def analyze(spot: float, iv: float, dte: int, lot_size: int, legs: list[dict]) -> dict:
    """legs: [{opt 'CE'/'PE', strike, side 'BUY'/'SELL', lots}]. Premiums are priced
    via BS at entry. Returns payoff curve + max profit/loss + breakevens + risk profile."""
    t = max(1e-6, float(dte) / 365.0)
    pos, payoff_legs = [], []
    for leg in legs:
        opt, K = leg["opt"], float(leg["strike"])
        lots = float(leg.get("lots", 1))
        sign = 1 if leg.get("side", "BUY") == "BUY" else -1
        qty = sign * lots * lot_size
        prem = round(bs_price(spot, K, t, R, max(1e-6, iv), opt), 2)
        pos.append({"S": spot, "K": K, "t": t, "iv": iv, "opt": opt, "qty": qty, "lot_size": 1})
        payoff_legs.append({"opt": opt, "K": K, "qty": qty, "entry_px": prem})
    curve = payoff_curve(payoff_legs, spot)
    risk = assess_structure(pos, spot, dte=int(dte))
    pnls = [p["pnl"] for p in curve] or [0.0]
    return {
        "spot": spot, "iv": iv, "dte": dte,
        "payoff": curve,
        "max_profit": round(max(pnls), 2),
        "max_loss": round(min(pnls), 2),
        "breakevens": _breakevens(curve),
        "net_greeks": risk["net_greeks"],
        "stress_var": risk["stress_var"],
        "span_margin": risk["span_margin"],
        "expiry_action": risk["expiry_action"],
    }
