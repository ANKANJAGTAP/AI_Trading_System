"""Live order lifecycle states + the pure terminal-state decision (P0#5).

A live entry can partial-fill or time out. The executor must cancel the resting
remainder, CONFIRM the cancel (never assume an order is dead on a poll timeout),
bracket only the confirmed filled quantity, and treat any unprotected live
exposure or unconfirmed remainder as a hard problem — block new entries + alert.
"""
from __future__ import annotations

SUBMITTED = "SUBMITTED"
PARTIAL_FILLED = "PARTIAL_FILLED"
CANCEL_REQUESTED = "CANCEL_REQUESTED"
CANCEL_CONFIRMED = "CANCEL_CONFIRMED"
BRACKET_PENDING = "BRACKET_PENDING"
PROTECTED = "PROTECTED"
UNPROTECTED = "UNPROTECTED"
RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
REJECTED = "REJECTED"

# Terminal states meaning live exposure may be unguarded -> block new entries + alert.
UNSAFE_STATES = frozenset({UNPROTECTED, RECONCILE_REQUIRED})


def entry_outcome(filled: int, requested: int, remainder_dealt_with: bool, bracket_ok: bool) -> str:
    """Terminal lifecycle state for a (possibly partial) live entry.

    - remainder_dealt_with: True if there is no resting remainder OR its cancel was
      CONFIRMED at the broker.
    - bracket_ok: a protective bracket/guard is in place for the filled qty.

    nothing filled + remainder dealt with -> REJECTED (clean no-fill);
    nothing filled + remainder NOT confirmed -> RECONCILE_REQUIRED (order may still fill);
    filled but remainder NOT confirmed -> RECONCILE_REQUIRED;
    filled + bracketed -> PROTECTED; filled + no bracket -> UNPROTECTED.
    """
    if filled <= 0:
        return REJECTED if remainder_dealt_with else RECONCILE_REQUIRED
    if not remainder_dealt_with:
        return RECONCILE_REQUIRED
    return PROTECTED if bracket_ok else UNPROTECTED
