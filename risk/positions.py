"""Open-position provider + aggregations for sleeve utilisation and portfolio heat.

The durable position book is built in Phase 3 (Execution); here we read open
positions from the `positions` table. A static provider is used for tests.
"""
from __future__ import annotations

from common.db import fetch


class PositionsProvider:
    async def open_positions(self) -> list[dict]:
        rows = await fetch(
            "SELECT correlation_id, instrument_token, tradingsymbol, sleeve, side, quantity, "
            "average_price, r_rupees FROM positions WHERE status = 'open'"
        )
        return [dict(r) for r in rows]


class StaticPositionsProvider(PositionsProvider):
    def __init__(self, positions: list[dict]) -> None:
        self._positions = positions

    async def open_positions(self) -> list[dict]:
        return list(self._positions)


def deployed_by_sleeve(positions: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in positions:
        qty = float(p.get("quantity") or 0)
        price = float(p.get("average_price") or 0)
        out[p.get("sleeve")] = out.get(p.get("sleeve"), 0.0) + qty * price
    return out


def total_open_r(positions: list[dict]) -> float:
    return sum(float(p.get("r_rupees") or 0) for p in positions)


def open_trades_count(positions: list[dict]) -> int:
    """Count TRADES, not rows: a multi-leg structure's legs share one correlation_id
    and must consume one concurrency slot, not one per leg."""
    seen, count = set(), 0
    for p in positions:
        cid = p.get("correlation_id")
        if cid is None:
            count += 1            # legacy/adopted rows without a correlation id
        elif cid not in seen:
            seen.add(cid)
            count += 1
    return count


def open_r_by_underlying(positions: list[dict], underlying: str) -> float:
    """Aggregate open R on one underlying across ALL its strikes/legs (prefix match
    on tradingsymbol, e.g. 'NIFTY' matches NIFTY2670723150PE). Stops the
    per-instrument cap being bypassed by stacking strikes of the same name."""
    u = (underlying or "").upper()
    if not u:
        return 0.0
    return sum(float(p.get("r_rupees") or 0) for p in positions
               if (p.get("tradingsymbol") or "").upper().startswith(u))
