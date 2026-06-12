"""Gamma Exposure (GEX) / dealer positioning (Phase 3.1).

Net GEX is the standard index-options regime read: positive => dealers are long
gamma and hedge AGAINST moves (vol-suppressing, mean-reverting); negative => they
hedge WITH moves (vol-amplifying, trending). Convention here (SqueezeMetrics-style):
call gamma adds, put gamma subtracts.

    GEX_strike = gamma * OI * contract_size * spot^2 * 0.01      (per 1% spot move)

Pure + testable: the caller passes the chain rows the option-chain endpoint already
builds (per-strike call/put gamma + OI), spot, and the lot size.
"""
from __future__ import annotations


def _leg_gex(leg: dict | None, spot: float, contract_size: float) -> float:
    if not leg:
        return 0.0
    gamma = float(leg.get("gamma") or 0.0)
    oi = float(leg.get("oi") or 0.0)
    return gamma * oi * contract_size * spot * spot * 0.01


def compute_gex(strikes: list[dict], spot: float, contract_size: float = 1.0) -> dict:
    """strikes: [{"strike", "call": {gamma, oi}|None, "put": {...}|None}, ...]."""
    by_strike: list[dict] = []
    net = 0.0
    for row in strikes:
        call_gex = _leg_gex(row.get("call"), spot, contract_size)
        put_gex = -_leg_gex(row.get("put"), spot, contract_size)
        sg = call_gex + put_gex
        net += sg
        by_strike.append({"strike": row["strike"], "gex": round(sg, 0)})

    call_wall = max(by_strike, key=lambda r: r["gex"], default=None)
    put_wall = min(by_strike, key=lambda r: r["gex"], default=None)
    return {
        "net_gex": round(net, 0),
        "regime": "positive_gamma" if net >= 0 else "negative_gamma",
        "by_strike": by_strike,
        "call_wall": call_wall["strike"] if call_wall else None,   # largest +gamma (resistance)
        "put_wall": put_wall["strike"] if put_wall else None,       # largest -gamma (support)
        "flip_strike": _gamma_flip(by_strike),
    }


def _gamma_flip(by_strike: list[dict]) -> float | None:
    """Approx zero-gamma level: the strike where cumulative GEX crosses zero."""
    cum = 0.0
    for i, row in enumerate(by_strike):
        prev = cum
        cum += row["gex"]
        if i > 0 and ((prev < 0 <= cum) or (prev > 0 >= cum)):
            return row["strike"]
    return None
