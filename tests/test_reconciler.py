"""P1#11 — reconciliation severity classifier (pure): a broker-only position is
the worst (flatten_required); any other diff blocks trading."""
from execution.reconciler import (FLATTEN_REQUIRED, INFO, TRADING_BLOCKED,
                                   classify_severity)


def test_no_mismatch_is_info():
    assert classify_severity([]) == INFO


def test_broker_only_position_is_flatten_required():
    # broker holds qty the book doesn't know about -> unprotected exposure
    assert classify_severity([{"instrument_token": 1, "book_qty": 0, "broker_qty": 50}]) == FLATTEN_REQUIRED


def test_qty_mismatch_is_trading_blocked():
    assert classify_severity([{"instrument_token": 1, "book_qty": 50, "broker_qty": 25}]) == TRADING_BLOCKED


def test_book_only_position_is_trading_blocked():
    # book has it, broker flat -> not a broker-only surprise, but still a drift
    assert classify_severity([{"instrument_token": 1, "book_qty": 50, "broker_qty": 0}]) == TRADING_BLOCKED
