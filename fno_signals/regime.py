"""
IV-regime routing — map a directional/vol view + the IV regime to a defined-risk
option-structure family (the plan's §9.2 table). Low IV favours buying premium
(debit spreads); high IV favours selling defined-risk premium (credit spreads /
condors). Credit selling can be blocked when IV is actively spiking.
"""
from __future__ import annotations


def iv_regime(iv_rank: float, low_max: float = 30.0, high_min: float = 60.0) -> str:
    if iv_rank < low_max:
        return "low"
    if iv_rank > high_min:
        return "high"
    return "mid"


_ROUTE = {
    ("bullish", "low"): "bull_call_debit",
    ("bullish", "mid"): "bull_call_debit",
    ("bullish", "high"): "bull_put_credit",
    ("bearish", "low"): "bear_put_debit",
    ("bearish", "mid"): "bear_put_debit",
    ("bearish", "high"): "bear_call_credit",
    ("neutral", "low"): "iron_condor",
    ("neutral", "mid"): "iron_condor",
    ("neutral", "high"): "iron_condor",
}

_CREDIT_FAMILIES = {"bull_put_credit", "bear_call_credit", "iron_condor"}


def route(direction: str, regime: str, iv_spiking: bool = False) -> str | None:
    """Return the structure family, or None if blocked (e.g. credit-sell during
    an IV spike — you don't want to be short vol into expanding vol)."""
    family = _ROUTE.get((direction, regime))
    if family is None:
        return None
    if iv_spiking and family in _CREDIT_FAMILIES:
        return None
    return family
