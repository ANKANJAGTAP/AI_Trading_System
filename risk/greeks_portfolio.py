"""Options-portfolio Greeks aggregation + limits (§10 Phase 5) — pure, no I/O.

Sums per-position Greeks (signed by quantity: qty<0 = short) into portfolio net
delta / gamma / vega / theta and flags limit breaches, so a basket of legs is
risk-managed as one book rather than leg-by-leg. Reuses the Black-Scholes Greeks in
`data/options.py`. r defaults to 6% (INR risk-free).

Position dict: {S, K, expiry(date) or t(years), iv(sigma e.g. 0.15), opt 'CE'/'PE',
qty(signed), lot_size}. A non-option leg (opt None/'FUT') is linear: delta ±1/unit.
"""
from __future__ import annotations

from data.options import greeks, year_fraction

R_DEFAULT = 0.06
_GREEKS = ("delta", "gamma", "vega", "theta")


def _t(pos: dict, now) -> float:
    if pos.get("t") is not None:
        return float(pos["t"])
    exp = pos.get("expiry")
    return year_fraction(exp, now) if exp is not None else 0.0


def position_greeks(pos: dict, r: float = R_DEFAULT, now=None) -> dict:
    """Signed Greeks for one position. Non-options are linear (delta = ±1 per unit)."""
    mult = float(pos.get("qty", 0)) * float(pos.get("lot_size", 1) or 1)
    opt = pos.get("opt")
    if opt not in ("CE", "PE"):
        return {"delta": mult, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
    g = greeks(float(pos["S"]), float(pos["K"]), _t(pos, now), r, float(pos["iv"]), opt)
    return {k: g[k] * mult for k in _GREEKS}


def portfolio_greeks(positions: list[dict], r: float = R_DEFAULT, now=None) -> dict:
    """Net book Greeks across all positions."""
    net = {k: 0.0 for k in _GREEKS}
    for p in positions:
        pg = position_greeks(p, r, now)
        for k in _GREEKS:
            net[k] += pg[k]
    return {k: round(v, 4) for k, v in net.items()}


def greek_limit_breaches(net: dict, limits: dict) -> dict:
    """limits: {greek: max_abs}. Returns {greek: {net, limit}} for each |net| over its cap."""
    breaches = {}
    for g, lim in (limits or {}).items():
        if lim is not None and abs(net.get(g, 0.0)) > float(lim):
            breaches[g] = {"net": round(net.get(g, 0.0), 4), "limit": float(lim)}
    return breaches
