"""#30 Instrument-metadata validation — pure helpers (no I/O).

Validate an order against the instrument master (lot size, tick size, freeze
quantity, expiry) BEFORE it is sent to the broker, so a malformed order is caught
locally instead of being rejected (or worse, mis-filled) at the exchange.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class OrderCheck:
    ok: bool
    reason: str = "ok"


def round_to_tick(price: float, tick_size: float | None) -> float:
    """Nearest valid price on the tick grid (no-op when tick_size is unknown)."""
    if not tick_size or tick_size <= 0:
        return price
    return round(round(price / tick_size) * tick_size, 10)


def tick_aligned(price: float, tick_size: float | None, tol: float = 1e-6) -> bool:
    if not tick_size or tick_size <= 0:
        return True
    return abs(price - round_to_tick(price, tick_size)) <= tol


def validate_order_against_meta(*, quantity, price=None, lot_size=None,
                                tick_size=None, freeze_qty=None, expiry=None,
                                today=None) -> OrderCheck:
    """Pre-submit order check. Unknown metadata fields are skipped (can't validate
    what we don't have), so this never blocks on missing data — only on a clear
    violation of known metadata."""
    if quantity is None or quantity <= 0:
        return OrderCheck(False, "non-positive quantity")
    if lot_size and lot_size > 0 and quantity % lot_size != 0:
        return OrderCheck(False, f"qty {quantity} not a multiple of lot {lot_size}")
    if freeze_qty and freeze_qty > 0 and quantity > freeze_qty:
        return OrderCheck(False, f"qty {quantity} exceeds freeze limit {freeze_qty}")
    if price is not None and not tick_aligned(price, tick_size):
        return OrderCheck(False, f"price {price} not aligned to tick {tick_size}")
    if expiry is not None and expiry < (today or dt.date.today()):
        return OrderCheck(False, f"contract expired {expiry}")
    return OrderCheck(True, "ok")
