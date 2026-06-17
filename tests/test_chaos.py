"""#40 — chaos / fault-injection. Inject the nasty cases (broker silence, malformed
rows, partial-then-cancel, bad ticks, crossed books, gap beyond the price band,
kill-switch active) and assert the system FAILS CLOSED everywhere: never fabricates a
fill, never books unclean P&L, never lets a new entry through under a halt, always
lets an exit out.
"""
from __future__ import annotations

from backtest.execution_model import freeze_slices, price_band_breached
from common.dataquality import validate_tick
from execution.order_lifecycle import RECONCILE_REQUIRED, UNPROTECTED, entry_outcome
from execution.policy import (close_books_fully, normalize_exit_status,
                              order_allowed, reduce_order_history)


# ----------------------------------------------------- broker silence / garbage
def test_reduce_tolerates_empty_and_malformed_history():
    for bad in ([], None, [{}], [{"status": None}], [{"foo": "bar"}]):
        rec = reduce_order_history(bad)
        assert rec["terminal"] is False and rec["filled"] == 0     # never terminal, never a fill
        assert close_books_fully(normalize_exit_status(rec["status"], rec["filled"]),
                                 rec["filled"], 100) is False       # never books


def test_unknown_status_never_books():
    for status in ("OPEN", "PUT ORDER REQ RECEIVED", "VALIDATION PENDING", "", None, "weird"):
        norm = normalize_exit_status(status, 0)
        assert close_books_fully(norm, 0, 75) is False


# ----------------------------------------------------- exits always escape a halt
def test_halt_blocks_entries_but_never_exits():
    for kill in (True, False):
        for block in (True, False):
            assert order_allowed("EXIT", kill, block) is True
            assert order_allowed("CANCEL", kill, block) is True
    assert order_allowed("ENTRY", True, False) is False            # kill-switch
    assert order_allowed("ENTRY", False, True) is False            # entries blocked


# ----------------------------------------------------- bad market data rejected
def test_bad_ticks_are_rejected():
    assert not validate_tick(0.0).ok                                # zero price
    assert not validate_tick(-1.0).ok
    assert not validate_tick(100.0, ts_age_s=120, max_age_s=30).ok  # stale
    assert not validate_tick(100.0, bid=101.0, ask=100.0).ok        # crossed book
    assert not validate_tick(500.0, prev_price=100.0).ok            # 5x jump
    assert not validate_tick(100.0, volume=-5).ok                   # negative volume
    assert validate_tick(100.0, prev_price=100.5, bid=99.9, ask=100.1, volume=10).ok


# ----------------------------------------------------- gap beyond band rejected
def test_gap_through_price_band_is_rejected():
    assert price_band_breached(140.0, 100.0, band_pct=0.20) is True
    assert price_band_breached(60.0, 100.0, band_pct=0.20) is True
    assert price_band_breached(110.0, 100.0, band_pct=0.20) is False


# ----------------------------------------------------- partial fills never over-book
def test_partial_or_cancelled_exit_never_books_clean():
    assert close_books_fully(normalize_exit_status("OPEN", 40), 40, 100) is False     # partial
    assert close_books_fully(normalize_exit_status("CANCELLED", 40), 40, 100) is False
    assert close_books_fully(normalize_exit_status("COMPLETE", 40), 40, 100) is False  # complete-but-short


def test_entry_fails_closed_when_remainder_unconfirmed():
    # filled something, but couldn't confirm the rest is dead -> reconcile, not protected
    assert entry_outcome(40, 100, remainder_dealt_with=False, bracket_ok=True) == RECONCILE_REQUIRED
    # filled, remainder dead, but NO bracket -> unprotected (blocks new entries upstream)
    assert entry_outcome(40, 100, remainder_dealt_with=True, bracket_ok=False) == UNPROTECTED


def test_freeze_slicing_never_exceeds_cap_under_any_qty():
    for q in (1, 899, 900, 901, 1800, 4500, 99999):
        slices = freeze_slices(q, 900)
        assert sum(slices) == q and all(s <= 900 for s in slices)
