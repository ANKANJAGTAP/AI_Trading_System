"""#38 — end-to-end paper replay.

Drives a multi-order session through the MockBroker exactly as the live executor
would (place_order -> poll order_history to terminal -> reduce -> normalize -> book
decision) and asserts the booking invariants hold across the whole sequence: only a
fully-COMPLETE fill books, partial/cancelled exits never fabricate P&L, and the
broker's net position reconciles to the book at the end.
"""
from __future__ import annotations

from broker.mock_broker import MockBroker
from execution.order_lifecycle import (PROTECTED, RECONCILE_REQUIRED, entry_outcome)
from execution.policy import (close_books_fully, normalize_exit_status,
                              reduce_order_history)


def _drive(mb: MockBroker, oid: str, max_polls: int = 10) -> dict:
    """Poll like the executor until terminal (or give up) and return the reduction."""
    rec = {"terminal": False, "status": None, "filled": 0}
    for _ in range(max_polls):
        rec = reduce_order_history(mb.order_history(oid))
        if rec["terminal"]:
            break
    return rec


def test_replay_books_only_complete_fills():
    # a session of exits across the full scenario matrix
    plan = [
        ("complete", True),               # books
        ("partial_then_complete", True),  # books (after 2 polls)
        ("partial_then_stuck", False),    # never books
        ("rejected", False),
        ("no_fill", False),
    ]
    mb = MockBroker()
    booked = 0
    for scenario, should_book in plan:
        oid = mb.place_order(tradingsymbol="INFY", exchange="NSE", transaction_type="SELL",
                             quantity=100, order_type="MARKET", scenario=scenario)
        rec = _drive(mb, oid)
        norm = normalize_exit_status(rec["status"], rec["filled"])
        books = close_books_fully(norm, rec["filled"], 100)
        assert books is should_book, (scenario, norm, rec["filled"])
        if books:
            booked += 1
    assert booked == 2


def test_replay_entry_lifecycle_and_position_reconciles():
    mb = MockBroker(default_scenario="complete")
    # two clean long entries, then flatten one
    a = mb.place_order(tradingsymbol="TCS", exchange="NSE", transaction_type="BUY", quantity=50)
    b = mb.place_order(tradingsymbol="TCS", exchange="NSE", transaction_type="BUY", quantity=25)
    for oid in (a, b):
        rec = _drive(mb, oid)
        assert entry_outcome(rec["filled"], 50 if oid == a else 25,
                             remainder_dealt_with=True, bracket_ok=True) == PROTECTED
    assert mb.net_quantity("TCS") == 75
    # exit 75 -> flat, and the broker truth reconciles
    ex = mb.place_order(tradingsymbol="TCS", exchange="NSE", transaction_type="SELL", quantity=75)
    _drive(mb, ex)
    assert mb.net_quantity("TCS") == 0


def test_replay_partial_then_cancel_is_reconcile_not_protected():
    mb = MockBroker(default_scenario="partial_then_stuck")
    oid = mb.place_order(tradingsymbol="WIPRO", exchange="NSE", transaction_type="BUY", quantity=100)
    rec = _drive(mb, oid, max_polls=3)
    # remainder NOT confirmed dead -> must be RECONCILE_REQUIRED (fail-closed), never PROTECTED
    assert entry_outcome(rec["filled"], 100, remainder_dealt_with=False, bracket_ok=True) == RECONCILE_REQUIRED
