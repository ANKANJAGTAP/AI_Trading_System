"""P0#4 — only a fully-COMPLETE broker exit books a clean P&L; everything else
goes to CLOSE_PENDING. (Pure decision helpers.)"""
from execution.policy import close_books_fully, normalize_exit_status


def test_normalize_exit_status():
    assert normalize_exit_status("COMPLETE", 75) == "COMPLETE"
    assert normalize_exit_status("REJECTED", 0) == "REJECTED"
    assert normalize_exit_status("CANCELLED", 0) == "REJECTED"
    assert normalize_exit_status("PARTIAL", 25) == "PARTIAL"
    assert normalize_exit_status("poll timeout", 10) == "PARTIAL"
    assert normalize_exit_status("poll timeout", 0) == "UNKNOWN"
    assert normalize_exit_status(None, 0) == "UNKNOWN"


def test_books_fully_only_on_complete_and_full():
    assert close_books_fully("COMPLETE", 75, 75)
    assert close_books_fully("COMPLETE", 80, 75)         # over-fill still fully closed
    assert not close_books_fully("COMPLETE", 50, 75)     # complete-but-short => pending
    assert not close_books_fully("PARTIAL", 75, 75)
    assert not close_books_fully("UNKNOWN", 0, 75)
    assert not close_books_fully("REJECTED", 0, 75)
