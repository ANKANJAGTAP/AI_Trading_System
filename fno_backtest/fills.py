"""
Fill models — how an order's execution price is simulated.

Two regimes (per the plan):
  * OHLC-only history -> best / mid / worst assumptions + a slippage budget.
    Default to WORST for any promotion decision; never assume mid on illiquid
    far strikes.
  * order-book available -> cross the book VWAP + slippage + beyond-book impact
    (mirrors the repo's live simulated_fill).
"""
from __future__ import annotations


def ohlc_fill(side: str, bar: dict, model: str = "worst",
              slippage_bps: float = 0.0) -> float:
    """Fill price from an OHLC bar. side in {BUY,SELL}."""
    side = side.upper()
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    if model == "close":
        base = c
    elif model == "open":
        base = o
    elif model == "mid":
        base = (h + l) / 2
    elif model == "worst":
        base = h if side == "BUY" else l        # adverse extreme
    elif model == "best":
        base = l if side == "BUY" else h
    else:
        raise ValueError(f"unknown fill model {model!r}")
    slip = base * slippage_bps / 10_000.0
    return base + slip if side == "BUY" else base - slip


def book_vwap_fill(side: str, book: list[tuple[float, int]], qty: int,
                   slippage_bps: float = 0.0, beyond_book_penalty: float = 2.0) -> float:
    """Cross an order book to fill `qty`.

    `book`: list of (price, size) levels on the side being crossed (asks for a
    BUY, bids for a SELL), best level first. If depth is insufficient, the
    remainder fills at the worst visible level plus an impact penalty.
    """
    side = side.upper()
    remaining = qty
    cost, taken = 0.0, 0
    worst = book[0][0] if book else 0.0
    for price, size in book:
        take = min(remaining, size)
        cost += take * price
        taken += take
        remaining -= take
        worst = price
        if remaining <= 0:
            break
    if remaining > 0:                       # beyond visible depth
        impact = worst * slippage_bps * beyond_book_penalty / 10_000.0
        px = worst + impact if side == "BUY" else worst - impact
        cost += remaining * px
        taken += remaining
    vwap = cost / taken if taken else worst
    slip = vwap * slippage_bps / 10_000.0
    return vwap + slip if side == "BUY" else vwap - slip
