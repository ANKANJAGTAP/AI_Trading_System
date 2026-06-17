"""#30 — instrument-metadata order validation (pure)."""
import datetime as dt

from common.instrument_meta import (round_to_tick, tick_aligned,
                                     validate_order_against_meta)
from execution.policy import entry_meta_block_reason  # #30 wiring gate


def test_valid_order_passes():
    c = validate_order_against_meta(quantity=50, price=100.05, lot_size=25,
                                    tick_size=0.05, freeze_qty=1800)
    assert c.ok, c.reason


def test_lot_multiple_enforced():
    assert not validate_order_against_meta(quantity=30, lot_size=25).ok
    assert validate_order_against_meta(quantity=75, lot_size=25).ok


def test_freeze_quantity_enforced():
    assert not validate_order_against_meta(quantity=2000, lot_size=25, freeze_qty=1800).ok


def test_tick_alignment_enforced():
    assert not validate_order_against_meta(quantity=25, price=100.03, lot_size=25, tick_size=0.05).ok
    assert validate_order_against_meta(quantity=25, price=100.05, lot_size=25, tick_size=0.05).ok


def test_expired_contract_blocked():
    today = dt.date(2026, 6, 17)
    assert not validate_order_against_meta(quantity=25, lot_size=25,
                                           expiry=dt.date(2026, 6, 10), today=today).ok
    assert validate_order_against_meta(quantity=25, lot_size=25,
                                       expiry=dt.date(2026, 6, 25), today=today).ok


def test_missing_metadata_does_not_block():
    # unknown lot/tick/freeze/expiry => only the qty>0 check applies
    assert validate_order_against_meta(quantity=33).ok


def test_round_to_tick_and_alignment():
    assert round_to_tick(100.03, 0.05) == 100.05
    assert tick_aligned(100.05, 0.05)
    assert tick_aligned(100.0, None)        # unknown tick => treated as aligned


# ---- #30 executor wiring gate (entry_meta_block_reason) ----
import datetime as dt


def test_entry_meta_sim_is_never_gated():
    # even a bad-lot / expired order is not blocked here in sim (paper unchanged)
    assert entry_meta_block_reason("simulated_fill", 30, None, {"lot_size": 25}, "MARKET") is None
    assert entry_meta_block_reason("simulated_fill", 25, None,
                                   {"lot_size": 25, "expiry": dt.date(2000, 1, 1)}, "MARKET") is None


def test_entry_meta_live_blocks_bad_lot_and_allows_good():
    assert entry_meta_block_reason("live", 30, None, {"lot_size": 25}, "MARKET")          # not a lot multiple
    assert entry_meta_block_reason("live", 75, None, {"lot_size": 25}, "MARKET") is None  # 3 lots, ok


def test_entry_meta_live_blocks_expired():
    r = entry_meta_block_reason("live", 25, None,
                                {"lot_size": 25, "expiry": dt.date(2000, 1, 1)}, "MARKET")
    assert r and "expired" in r


def test_entry_meta_tick_only_enforced_for_limit():
    inst = {"lot_size": 25, "tick_size": 0.05}
    assert entry_meta_block_reason("live", 25, 100.03, inst, "MARKET") is None  # market ignores price
    assert entry_meta_block_reason("live", 25, 100.03, inst, "LIMIT")          # limit must align to tick
