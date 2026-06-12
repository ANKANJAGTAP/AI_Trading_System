"""Realistic fill simulation (spec §8): real live bid/ask + slippage + cost model,
no real order sent. BUY fills at the ask, SELL at the bid, plus modelled slippage.

Depth-aware: the fill walks the visible order book for OUR quantity (size-weighted
average across levels), so size pays for liquidity instead of everything magically
filling at top-of-book. Quantity beyond the visible book pays an extra impact
penalty. Flat `slippage_bps` is then added on top (latency / adverse selection).
"""
from __future__ import annotations

from common.logging import get_logger
from common.market_time import now_ist
from execution.costs import CostModel
from execution.models import Decision, Fill

log = get_logger("simulator")

# Quantity that doesn't fit in the visible 5-level book pays this multiple of the
# normal slippage on top of the worst visible level (market-impact proxy).
_BEYOND_BOOK_PENALTY = 5.0


class FillSimulator:
    def __init__(self, config, cost_model: CostModel, adapter, governor) -> None:
        self.slippage_bps = float(config.execution.slippage_bps)
        self.cost = cost_model
        self.adapter = adapter
        self.governor = governor

    async def quote_depth(self, instrument: dict, side: str) -> tuple[list[tuple[float, int]], float | None]:
        """Order-book levels on the side we'd cross (sell book for BUY, buy book for
        SELL) as [(price, qty), ...], plus last_price as a fallback."""
        key = f"{instrument['exchange']}:{instrument['tradingsymbol']}"
        try:
            quote = await self.governor.call("quote", self.adapter.quote, [key])
            data = quote.get(key) or {}
            depth = data.get("depth") or {}
            book = depth.get("sell") if side == "BUY" else depth.get("buy")
            levels = [(float(lv["price"]), int(lv.get("quantity") or 0))
                      for lv in (book or []) if lv.get("price")]
            last = data.get("last_price")
            return [lv for lv in levels if lv[0] > 0 and lv[1] > 0], (float(last) if last else None)
        except Exception as exc:
            log.warning("sim_quote_failed", error=str(exc))
            return [], None

    async def quote_price(self, instrument: dict, side: str) -> float | None:
        """Top-of-book price on the crossing side (kept for single-unit callers)."""
        levels, last = await self.quote_depth(instrument, side)
        return levels[0][0] if levels else last

    async def fill_price(self, instrument: dict, side: str, qty: int) -> float | None:
        """Size-aware fill: VWAP across the visible book for `qty`, impact penalty
        beyond it, then flat slippage on top. None when there is no price at all."""
        levels, last = await self.quote_depth(instrument, side)
        if not levels:
            if not last:
                return None
            px = last
        else:
            remaining = max(1, int(qty))
            notional = 0.0
            filled = 0
            for price, avail in levels:
                take = min(remaining, avail)
                notional += take * price
                filled += take
                remaining -= take
                if remaining <= 0:
                    break
            if remaining > 0:
                # the rest pays the worst visible level + an impact penalty
                worst = levels[-1][0]
                pen = worst * self.slippage_bps * _BEYOND_BOOK_PENALTY / 10000.0
                px_beyond = worst + pen if side == "BUY" else worst - pen
                notional += remaining * px_beyond
                filled += remaining
            px = notional / filled
        slip = px * self.slippage_bps / 10000.0
        return round(px + slip if side == "BUY" else px - slip, 2)

    async def simulate(self, decision: Decision, fill_qty: int | None = None) -> Fill | None:
        side = decision.side
        qty = fill_qty or decision.quantity
        # Entries fill ONLY against live market data. No fallback to the signal's
        # entry_price — that would invent a fill at a stale/imagined price.
        fill_px = await self.fill_price(decision.instrument, side, qty)
        if not fill_px:
            return None
        seg = self.cost.segment_key(decision.sleeve, decision.instrument.get("instrument_type"))
        fees = self.cost.compute_leg(seg, side, qty, fill_px)
        return Fill(quantity=qty, price=fill_px, fees=fees, ts=now_ist())
