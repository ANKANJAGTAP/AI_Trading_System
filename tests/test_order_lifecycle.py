"""P0#5 — partial/timeout live entries never leave unguarded exposure: the
terminal-state decision is pure and exhaustively tested."""
from execution.order_lifecycle import (PROTECTED, RECONCILE_REQUIRED, REJECTED,
                                        UNPROTECTED, UNSAFE_STATES, entry_outcome)


def test_clean_no_fill_is_rejected():
    assert entry_outcome(0, 75, remainder_dealt_with=True, bracket_ok=False) == REJECTED


def test_no_fill_unconfirmed_remainder_reconcile():
    assert entry_outcome(0, 75, remainder_dealt_with=False, bracket_ok=False) == RECONCILE_REQUIRED


def test_filled_unconfirmed_remainder_reconcile():
    assert entry_outcome(50, 75, remainder_dealt_with=False, bracket_ok=True) == RECONCILE_REQUIRED


def test_filled_and_bracketed_is_protected():
    assert entry_outcome(75, 75, remainder_dealt_with=True, bracket_ok=True) == PROTECTED
    # partial but remainder confirmed-cancelled and the filled qty is bracketed
    assert entry_outcome(50, 75, remainder_dealt_with=True, bracket_ok=True) == PROTECTED


def test_filled_without_bracket_is_unprotected():
    assert entry_outcome(75, 75, remainder_dealt_with=True, bracket_ok=False) == UNPROTECTED


def test_unsafe_states_membership():
    assert UNPROTECTED in UNSAFE_STATES and RECONCILE_REQUIRED in UNSAFE_STATES
    assert PROTECTED not in UNSAFE_STATES and REJECTED not in UNSAFE_STATES
