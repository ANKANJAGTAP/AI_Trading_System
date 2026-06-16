"""Pure execution-policy helpers — no I/O, safe to import anywhere (incl. tests)."""
from __future__ import annotations


def live_structures_block_reason(mode: str, enabled: bool) -> str | None:
    """P0#6: live multi-leg F&O is not implemented for real orders. Sim is always
    allowed; live is blocked unless explicitly enabled, and even then fails closed
    (there is no live basket lifecycle yet). Returns a reason when blocked, else None."""
    if mode != "live":
        return None
    if not enabled:
        return "F&O structures are paper-only (set execution.fno_live_structures_enabled to enable)"
    return "live F&O structures enabled in config but not implemented (fail-closed)"
