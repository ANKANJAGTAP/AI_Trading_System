"""Scenario / stress VaR for an options book (§10 Phase 3/5) — pure, no I/O.

Greeks are a local (first/second-order) approximation; this fully REPRICES every
position across a grid of spot shocks × vol shocks via Black-Scholes, so the book's
worst-case loss is measured, not estimated. The core options-portfolio risk gate.

`spot_shock` is a fraction (0.05 = +5%); `vol_shock` is in vol POINTS (3 = +3 pts,
i.e. sigma 0.15 -> 0.18). Position dict is the same shape as greeks_portfolio.
"""
from __future__ import annotations

from data.options import bs_price, year_fraction

R_DEFAULT = 0.06
DEFAULT_SPOT_SHOCKS = (-0.06, -0.03, 0.0, 0.03, 0.06)
DEFAULT_VOL_SHOCKS = (-3.0, 0.0, 3.0)


def _t(pos: dict, now) -> float:
    if pos.get("t") is not None:
        return float(pos["t"])
    exp = pos.get("expiry")
    return year_fraction(exp, now) if exp is not None else 0.0


def _price(pos: dict, S: float, sigma: float, r: float, now) -> float:
    opt = pos.get("opt")
    if opt not in ("CE", "PE"):
        return float(S)                      # linear instrument tracks spot
    return bs_price(S, float(pos["K"]), _t(pos, now), r, max(1e-6, sigma), opt)


def position_pnl(pos: dict, spot_shock: float, vol_shock: float,
                 r: float = R_DEFAULT, now=None) -> float:
    """P&L of one position under a (spot_shock, vol_shock) move, repriced via BS."""
    S0, sig0 = float(pos["S"]), float(pos.get("iv", 0.0))
    mult = float(pos.get("qty", 0)) * float(pos.get("lot_size", 1) or 1)
    p0 = _price(pos, S0, sig0, r, now)
    p1 = _price(pos, S0 * (1 + spot_shock), sig0 + vol_shock / 100.0, r, now)
    return (p1 - p0) * mult


def scenario_pnl(positions: list[dict], spot_shock: float, vol_shock: float,
                 r: float = R_DEFAULT, now=None) -> float:
    return round(sum(position_pnl(p, spot_shock, vol_shock, r, now) for p in positions), 2)


def stress_grid(positions: list[dict], spot_shocks=DEFAULT_SPOT_SHOCKS,
                vol_shocks=DEFAULT_VOL_SHOCKS, r: float = R_DEFAULT, now=None) -> dict:
    return {(round(s, 4), round(v, 4)): scenario_pnl(positions, s, v, r, now)
            for s in spot_shocks for v in vol_shocks}


def stress_var(positions: list[dict], spot_shocks=DEFAULT_SPOT_SHOCKS,
               vol_shocks=DEFAULT_VOL_SHOCKS, r: float = R_DEFAULT, now=None) -> dict:
    """Worst-case loss across the scenario grid. {stress_var, worst_scenario, grid_points}.
    stress_var is the minimum (most negative) scenario P&L."""
    grid = stress_grid(positions, spot_shocks, vol_shocks, r, now)
    if not grid:
        return {"stress_var": 0.0, "worst_scenario": None, "grid_points": 0}
    worst = min(grid, key=grid.get)
    return {"stress_var": round(grid[worst], 2), "worst_scenario": worst,
            "grid_points": len(grid)}
