"""Pre-trade risk assessment for an options structure (§10 Phase 5 integration) — pure.

Composes the Phase 5 engines into one verdict for a multi-leg structure: net book
Greeks, scenario/stress VaR (full BS repricing), SPAN-style scan margin, and an
expiry/pin action — plus an overall block/allow with reasons. Wired into the paper
F&O sim so every structure is risk-checked the way a live options book would be,
without touching the live equity path.

`legs`: position dicts {S, K, t(years) or expiry(date), iv, opt 'CE'/'PE', qty(signed),
lot_size}. `dte` (optional) overrides per-leg days-to-expiry for the expiry check
(the F&O engine already knows DTE, so it passes it in).
"""
from __future__ import annotations

from backtest.span_margin import span_margin
from risk.expiry_control import days_to_expiry, expiry_action, moneyness
from risk.greeks_portfolio import greek_limit_breaches, portfolio_greeks
from risk.scenario_var import stress_var


def _leg_dte(leg: dict, today) -> int:
    if leg.get("expiry") is not None:
        return days_to_expiry(leg["expiry"], today)
    if leg.get("t") is not None:
        return int(round(float(leg["t"]) * 365))
    return 99


def assess_structure(legs: list[dict], spot: float, *, dte: int | None = None,
                     greek_limits: dict | None = None, max_stress_loss: float | None = None,
                     now=None, today=None) -> dict:
    """Return {net_greeks, stress_var, span_margin, expiry_action, greek_breaches,
    blocked, reason}. `blocked` is True if any Greek limit is breached, stress-VaR is
    worse than -max_stress_loss, or an expiry rule says block."""
    net = portfolio_greeks(legs, now=now)
    sv = stress_var(legs, now=now)["stress_var"]
    margin = span_margin(legs, now=now)["margin"]

    reasons: list[str] = []
    breaches = greek_limit_breaches(net, greek_limits or {})
    if breaches:
        reasons.append("greek_limits:" + ",".join(sorted(breaches)))
    if max_stress_loss is not None and sv < -abs(max_stress_loss):
        reasons.append(f"stress_var {sv} worse than -{abs(max_stress_loss)}")

    actions = []
    for leg in legs:
        if leg.get("opt") not in ("CE", "PE"):
            continue
        d = dte if dte is not None else _leg_dte(leg, today)
        actions.append(expiry_action(d, moneyness(spot, float(leg["K"])),
                                     float(leg.get("qty", 0)) < 0))
    expiry = "block" if "block" in actions else ("reduce" if "reduce" in actions else "allow")
    if expiry == "block":
        reasons.append("expiry_block")

    return {
        "net_greeks": net,
        "stress_var": sv,
        "span_margin": margin,
        "expiry_action": expiry,
        "greek_breaches": breaches,
        "blocked": bool(reasons),
        "reason": "; ".join(reasons),
    }
