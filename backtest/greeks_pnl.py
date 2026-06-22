"""Greeks P&L attribution (§10 Phase 3) — pure, no I/O.

Decomposes a position's P&L over a step into delta / gamma / vega / theta
contributions (a second-order Taylor expansion) plus the unexplained residual, so a
day's option P&L can be read as "made on direction, gave back on theta, etc."

Greeks are per-unit as produced by `data/options.greeks`: delta/gamma per 1 point of
underlying, vega per 1 vol-point, theta per calendar day. `mult` = signed qty*lot_size.
"""
from __future__ import annotations


def attribute_pnl(g: dict, dS: float, dVol_pts: float, dDays: float,
                  actual_pnl: float | None = None, mult: float = 1.0) -> dict:
    """Return {delta, gamma, vega, theta, explained[, residual, actual]} P&L pieces."""
    delta_pnl = g.get("delta", 0.0) * dS
    gamma_pnl = 0.5 * g.get("gamma", 0.0) * dS * dS
    vega_pnl = g.get("vega", 0.0) * dVol_pts
    theta_pnl = g.get("theta", 0.0) * dDays
    explained = (delta_pnl + gamma_pnl + vega_pnl + theta_pnl) * mult
    out = {
        "delta": round(delta_pnl * mult, 4),
        "gamma": round(gamma_pnl * mult, 4),
        "vega": round(vega_pnl * mult, 4),
        "theta": round(theta_pnl * mult, 4),
        "explained": round(explained, 4),
    }
    if actual_pnl is not None:
        out["actual"] = round(actual_pnl, 4)
        out["residual"] = round(actual_pnl - explained, 4)
    return out
