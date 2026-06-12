"""Open-interest buildup classification (spec §5.2 / handbook §8).

The price-change x OI-change matrix is the core F&O directional read:

    price up   + OI up    -> long buildup     (bullish, fresh longs)
    price down + OI up    -> short buildup     (bearish, fresh shorts)
    price up   + OI down   -> short covering    (bullish, shorts exiting)
    price down + OI down   -> long unwinding     (bearish, longs exiting)

The labels are operator-tunable in config/strategy_params.yaml (fno.oi_buildup); the
defaults below match the spec. `buildup_bias` collapses a label to a directional
vote the FNO pipeline's direction/OI gate can confirm against.
"""
from __future__ import annotations

_DEFAULT_MATRIX = {
    "price_up_oi_up": "long_buildup_bullish",
    "price_down_oi_up": "short_buildup_bearish",
    "price_up_oi_down": "short_covering",
    "price_down_oi_down": "long_unwinding",
}

_BULLISH = {"long_buildup_bullish", "short_covering"}
_BEARISH = {"short_buildup_bearish", "long_unwinding"}


def classify_buildup(price_change: float, oi_change: float, matrix: dict | None = None,
                     eps: float = 0.0) -> str:
    """Map (price_change, oi_change) to a buildup label. Returns 'neutral' when either
    change is within +/-eps (flat)."""
    m = {**_DEFAULT_MATRIX, **(matrix or {})}
    if abs(price_change) <= eps or abs(oi_change) <= eps:
        return "neutral"
    if price_change > 0 and oi_change > 0:
        return m["price_up_oi_up"]
    if price_change < 0 and oi_change > 0:
        return m["price_down_oi_up"]
    if price_change > 0 and oi_change < 0:
        return m["price_up_oi_down"]
    return m["price_down_oi_down"]


def buildup_bias(label: str) -> str:
    """Collapse a buildup label to 'bullish' / 'bearish' / 'neutral'."""
    if label in _BULLISH:
        return "bullish"
    if label in _BEARISH:
        return "bearish"
    return "neutral"
