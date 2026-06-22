"""SPAN-style scan-risk margin (§10 Phase 3) — pure, no I/O.

A simplified SPAN: scan the portfolio's loss across a standard array of risk
scenarios (spot moved across ±scan_range in steps, each at vol up and vol down) and
take the worst loss as the scan-risk margin. This captures the non-linear option risk
a flat %-of-notional margin misses — e.g. a short-gamma book whose loss accelerates on
a big move. Reuses the BS repricing in `risk.scenario_var`.
"""
from __future__ import annotations

from risk.scenario_var import R_DEFAULT, scenario_pnl


def scan_scenarios(scan_range_pct: float = 0.06, vol_shift_pts: float = 3.0,
                   n_steps: int = 3) -> list[tuple]:
    """The SPAN-like scenario array: spot across ±scan_range in 2*n_steps+1 steps,
    each combined with vol up and vol down."""
    spots = [scan_range_pct * i / n_steps for i in range(-n_steps, n_steps + 1)]
    vols = [vol_shift_pts, -vol_shift_pts]
    return [(s, v) for s in spots for v in vols]


def span_margin(positions: list[dict], scan_range_pct: float = 0.06,
                vol_shift_pts: float = 3.0, n_steps: int = 3,
                r: float = R_DEFAULT, now=None) -> dict:
    """Scan-risk margin = the worst loss across the scenario array (returned positive).
    {margin, worst_scenario, scenarios}."""
    worst_pnl, worst_scn = 0.0, None
    for s, v in scan_scenarios(scan_range_pct, vol_shift_pts, n_steps):
        pnl = scenario_pnl(positions, s, v, r, now)
        if pnl < worst_pnl:
            worst_pnl, worst_scn = pnl, (round(s, 4), round(v, 4))
    return {"margin": round(-worst_pnl, 2), "worst_scenario": worst_scn,
            "scenarios": (2 * n_steps + 1) * 2}
