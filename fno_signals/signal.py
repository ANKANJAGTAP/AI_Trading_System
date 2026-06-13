"""
Primary signal generation — a transparent, rule-based directional/vol view from
the feature vector. This is the PRIMARY model in the meta-labelling scheme: it
decides direction and whether to act; the secondary (meta) model later only
sizes or vetoes it (Pillar 3). Kept deterministic and inspectable on purpose.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Signal:
    underlying: str
    direction: str                 # 'bullish' | 'bearish' | 'neutral'
    view_strength: float           # 0..1 raw conviction (pre meta-label)
    rationale: dict = field(default_factory=dict)


def generate_signal(ctx) -> Signal:
    """Combine trend, momentum and regime features into a directional view.

    Uses point-in-time features from MarketContext. Missing features are treated
    as neutral so the engine degrades gracefully on partial data.
    """
    f = ctx.features
    dma = f.get("dma_dist_200", 0.0)      # % above/below 200DMA
    macd = f.get("macd_hist", 0.0)
    adx = f.get("adx_14", 0.0)
    rsi = f.get("rsi_14", 50.0)
    st = f.get("supertrend_dir", 0.0)

    bull = 0.0
    bear = 0.0
    # trend
    if dma > 0:
        bull += 1
    elif dma < 0:
        bear += 1
    # momentum
    if macd > 0:
        bull += 1
    elif macd < 0:
        bear += 1
    if st > 0:
        bull += 1
    elif st < 0:
        bear += 1
    # exhaustion guard
    if rsi >= 75:
        bull -= 0.5
    elif rsi <= 25:
        bear -= 0.5

    trend_quality = min(max((adx - 15) / 25.0, 0.0), 1.0)  # 0 at ADX<=15, 1 at >=40

    if bull > bear and bull >= 2:
        direction = "bullish"
        strength = min(bull / 3.0, 1.0) * (0.5 + 0.5 * trend_quality)
    elif bear > bull and bear >= 2:
        direction = "bearish"
        strength = min(bear / 3.0, 1.0) * (0.5 + 0.5 * trend_quality)
    else:
        direction = "neutral"
        # neutral conviction is higher when trend is weak (good for range/condor)
        strength = 0.5 * (1.0 - trend_quality)

    return Signal(
        underlying=ctx.underlying,
        direction=direction,
        view_strength=round(float(max(strength, 0.0)), 4),
        rationale={"dma_dist_200": dma, "macd_hist": macd, "adx_14": adx,
                   "rsi_14": rsi, "supertrend_dir": st},
    )
