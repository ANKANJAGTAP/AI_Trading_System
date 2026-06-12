"""Order-flow read (Phase 3.4): top-of-book imbalance from the depth ladder.

Cheap, robust intraday pressure read from the live depth Kite already gives us
(true tick cumulative-delta needs trade-by-trade classification we don't archive,
so it's intentionally out of scope). Pure.
"""
from __future__ import annotations


def book_imbalance(bids: list[dict] | None, asks: list[dict] | None, depth: int = 5) -> dict:
    """imbalance = (bidQty - askQty) / (bidQty + askQty) over the top `depth` levels."""
    bq = sum(float(b.get("quantity", 0) or 0) for b in (bids or [])[:depth])
    aq = sum(float(a.get("quantity", 0) or 0) for a in (asks or [])[:depth])
    total = bq + aq
    if total <= 0:
        return {"bid_qty": 0.0, "ask_qty": 0.0, "imbalance": 0.0, "bias": "neutral"}
    imb = (bq - aq) / total
    bias = "buy" if imb > 0.2 else ("sell" if imb < -0.2 else "neutral")
    return {"bid_qty": round(bq, 0), "ask_qty": round(aq, 0), "imbalance": round(imb, 3), "bias": bias}
