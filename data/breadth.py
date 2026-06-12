"""Market breadth (Phase 2.3): advance/decline across the tracked universe — a
market-wide regime input the per-instrument context can't see on its own.
"""
from __future__ import annotations

from data.store import load_candles_df


def classify_breadth(changes: list[float], eps: float = 0.0) -> dict:
    """Summarise a list of per-symbol % day-changes into breadth stats (pure)."""
    adv = sum(1 for c in changes if c > eps)
    dec = sum(1 for c in changes if c < -eps)
    total = len(changes)
    flat = total - adv - dec
    ad_ratio = round(adv / dec, 2) if dec else (float(adv) if adv else 0.0)
    adv_pct = round(adv / total * 100, 1) if total else 0.0
    if adv > dec * 1.5:
        bias = "bullish"
    elif dec > adv * 1.5:
        bias = "bearish"
    else:
        bias = "neutral"
    return {"advances": adv, "declines": dec, "flat": flat, "total": total,
            "ad_ratio": ad_ratio, "adv_pct": adv_pct, "bias": bias}


async def market_breadth(tokens: list[int]) -> dict:
    """Live breadth from the latest two daily candles of each token."""
    changes: list[float] = []
    for tok in tokens:
        if not tok:
            continue
        try:
            df = await load_candles_df(tok, "day", 2)
            if len(df) >= 2:
                prev, last = float(df["close"].iloc[-2]), float(df["close"].iloc[-1])
                if prev:
                    changes.append((last - prev) / prev * 100.0)
        except Exception:
            continue
    return classify_breadth(changes)
