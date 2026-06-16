"""Pure execution-policy helpers — no I/O, safe to import anywhere (incl. tests)."""
from __future__ import annotations

# P0#3: (exchange, product) pairs we can correctly place AND exit live. Anything
# outside this set fails closed — at entry (don't open what we can't exit) and at
# exit (don't blind-fire an MIS market order on a CNC/NRML position).
SUPPORTED_EXIT_PRODUCTS = frozenset({
    ("NSE", "MIS"), ("NSE", "CNC"),
    ("BSE", "MIS"), ("BSE", "CNC"),
    ("NFO", "NRML"), ("NFO", "MIS"),
    ("MCX", "NRML"),
})


def exit_product_supported(exchange: str | None, product: str | None) -> bool:
    """True if we can place + exit a live position on this (exchange, product)."""
    return (exchange, product) in SUPPORTED_EXIT_PRODUCTS


def normalize_exit_status(poll_status: str | None, filled: int) -> str:
    """P0#4: map a broker order-history status to a NormalizedFill status."""
    if poll_status == "COMPLETE":
        return "COMPLETE"
    if poll_status in ("REJECTED", "CANCELLED"):
        return "REJECTED"
    return "PARTIAL" if filled > 0 else "UNKNOWN"


def close_books_fully(status: str, filled_qty: int, position_qty: int) -> bool:
    """P0#4: only a fully-COMPLETE broker exit may book a clean realized P&L. Any
    partial / unknown / rejected exit must go to CLOSE_PENDING (no fabricated P&L)."""
    return status == "COMPLETE" and filled_qty >= position_qty


def live_structures_block_reason(mode: str, enabled: bool) -> str | None:
    """P0#6: live multi-leg F&O is not implemented for real orders. Sim is always
    allowed; live is blocked unless explicitly enabled, and even then fails closed
    (there is no live basket lifecycle yet). Returns a reason when blocked, else None."""
    if mode != "live":
        return None
    if not enabled:
        return "F&O structures are paper-only (set execution.fno_live_structures_enabled to enable)"
    return "live F&O structures enabled in config but not implemented (fail-closed)"
