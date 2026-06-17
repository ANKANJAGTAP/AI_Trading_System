"""#41 — property-style invariant tests for the pure risk/policy/data gates.

These don't check one example; they sweep a parameter grid and assert properties
that must hold for *every* point — the kind of guarantee a trading risk layer lives
or dies by (never risk more than budgeted, exits are never blocked, a clamped size
is never larger than its cap). Pure functions only: no DB, no Redis, no new
dependency (plain itertools grids + pytest).
"""
from __future__ import annotations

import datetime as dt
import itertools

from common.dataquality import validate_tick
from common.instrument_meta import (round_to_tick, tick_aligned,
                                     validate_order_against_meta)
from execution.policy import (SUPPORTED_EXIT_PRODUCTS, close_books_fully,
                              entry_meta_block_reason, exit_product_supported,
                              live_structures_block_reason, order_allowed)
from risk.models import InstrumentKind
from risk.sizing import floor_to_lot, size_position

EPS = 1e-6


# --------------------------------------------------------------- order_allowed
def test_exits_and_cancels_are_never_blocked():
    """The cardinal safety invariant: whatever the kill-switch / entry-block state,
    EXIT and CANCEL must always be permitted so open risk can always be closed."""
    for intent, kill, block, mode in itertools.product(
        ("EXIT", "CANCEL"), (True, False), (True, False),
        ("block_all", "halt_everything", "soft"),
    ):
        assert order_allowed(intent, kill, block, mode) is True, (intent, kill, block, mode)


def test_entries_blocked_exactly_when_kill_or_block_set():
    for kill, block, mode in itertools.product(
        (True, False), (True, False), ("block_all", "soft"),
    ):
        expected = not (kill or block)
        assert order_allowed("ENTRY", kill, block, mode) is expected, (kill, block, mode)


# --------------------------------------------------------------- size_position
_CAPITALS = (100_000.0, 1_000_000.0, 10_000_000.0)
_PCTS = (0.5, 1.0, 2.0)
_ENTRIES = (50.0, 100.0, 2500.0)
_STOP_FRACS = (0.005, 0.02, 0.05)
_LOTS = (1, 25, 50)
_CONFS = (0.25, 0.5, 1.0)
_CAPS = (5.0, 15.0, 100.0)


def _grid():
    return itertools.product(_CAPITALS, _PCTS, _ENTRIES, _STOP_FRACS, _LOTS, _CONFS, _CAPS)


def test_size_never_exceeds_risk_budget_or_instrument_cap():
    """For every accepted size: actual ₹ at risk never exceeds the (confidence-scaled)
    R budget, and allocated capital never exceeds the per-instrument notional cap.
    A clamp can only ever make a position SMALLER."""
    checked = 0
    for cap, pct, entry, sf, lot, conf, cappct in _grid():
        stop = entry * (1 - sf)
        r = size_position(
            capital=cap, per_trade_risk_pct=pct, per_instrument_cap_pct=cappct,
            entry_price=entry, stop_price=stop, lot_size=lot,
            kind=InstrumentKind.EQUITY, confidence=conf,
        )
        if r.rejected:
            assert r.quantity == 0
            continue
        checked += 1
        risk_budget = cap * pct / 100.0 * conf
        notional_cap = cappct / 100.0 * cap
        assert r.quantity > 0
        assert r.quantity % lot == 0, (r.quantity, lot)
        assert r.actual_risk <= risk_budget + EPS, (r.actual_risk, risk_budget)
        assert r.capital_allocated <= notional_cap + EPS, (r.capital_allocated, notional_cap)
        # internal consistency: risk == units * |entry-stop|, capital == units * entry
        assert abs(r.actual_risk - r.quantity * (entry - stop)) < 1e-3
        assert abs(r.capital_allocated - r.quantity * entry) < 1e-3
    assert checked > 100, f"grid produced too few accepted sizes ({checked})"


def test_size_is_monotonic_non_decreasing_in_confidence():
    """More conviction never yields a smaller position (all else equal)."""
    for cap, pct, entry, sf, lot, cappct in itertools.product(
        _CAPITALS, _PCTS, _ENTRIES, _STOP_FRACS, _LOTS, _CAPS,
    ):
        stop = entry * (1 - sf)
        prev = -1
        for conf in (0.1, 0.25, 0.5, 0.75, 1.0):
            q = size_position(
                capital=cap, per_trade_risk_pct=pct, per_instrument_cap_pct=cappct,
                entry_price=entry, stop_price=stop, lot_size=lot, confidence=conf,
            ).quantity
            assert q >= prev, (conf, q, prev)
            prev = q


def test_size_is_monotonic_non_decreasing_in_capital():
    """More capital never yields a smaller position (all else equal)."""
    for pct, entry, sf, lot, cappct, conf in itertools.product(
        _PCTS, _ENTRIES, _STOP_FRACS, _LOTS, _CAPS, _CONFS,
    ):
        stop = entry * (1 - sf)
        prev = -1
        for cap in (50_000.0, 250_000.0, 1_000_000.0, 5_000_000.0):
            q = size_position(
                capital=cap, per_trade_risk_pct=pct, per_instrument_cap_pct=cappct,
                entry_price=entry, stop_price=stop, lot_size=lot, confidence=conf,
            ).quantity
            assert q >= prev, (cap, q, prev)
            prev = q


def test_portfolio_remaining_r_caps_actual_risk():
    """When a portfolio risk budget is supplied, the position's ₹-at-risk respects it."""
    for rem in (1_000.0, 5_000.0, 20_000.0):
        r = size_position(
            capital=10_000_000.0, per_trade_risk_pct=2.0, per_instrument_cap_pct=100.0,
            entry_price=100.0, stop_price=99.0, lot_size=1,
            portfolio_remaining_r=rem,
        )
        if not r.rejected:
            assert r.actual_risk <= rem + EPS, (r.actual_risk, rem)


def test_margin_caps_allocated_capital():
    """A live-margin ceiling is never exceeded by the sized position."""
    for margin in (10_000.0, 100_000.0, 1_000_000.0):
        r = size_position(
            capital=10_000_000.0, per_trade_risk_pct=2.0, per_instrument_cap_pct=100.0,
            entry_price=100.0, stop_price=99.0, lot_size=1,
            margin_available=margin, margin_per_unit=100.0,
        )
        if not r.rejected:
            assert r.quantity * 100.0 <= margin + EPS, (r.quantity, margin)


def test_size_rejects_degenerate_inputs():
    base = dict(per_trade_risk_pct=1.0, per_instrument_cap_pct=15.0,
                entry_price=100.0, stop_price=99.0, lot_size=1)
    assert size_position(capital=0.0, **base).rejected            # no capital
    assert size_position(capital=1_000_000.0, **{**base, "confidence": 0.0}).rejected
    # zero stop distance
    assert size_position(capital=1_000_000.0, per_trade_risk_pct=1.0,
                         per_instrument_cap_pct=15.0, entry_price=100.0,
                         stop_price=100.0).rejected


def test_floor_to_lot_properties():
    for u in (-5.0, 0.0, 0.4, 1.0, 26.7, 999.9):
        for lot in (1, 5, 25, 50):
            out = floor_to_lot(u, lot)
            assert out >= 0
            assert out <= max(0.0, u) + EPS          # never rounds up
            if lot > 1 and out > 0:
                assert out % lot == 0                # always a clean lot multiple


# --------------------------------------------------------------- data quality
def test_good_ticks_pass_and_bad_ticks_fail():
    # a clean tick is accepted across a range of sane values (prev close to price)
    for price in (1.0, 100.0, 5000.0):
        for prev in (None, price * 0.99):
            assert validate_tick(price, prev_price=prev, ts_age_s=1.0,
                                 bid=price - 0.05, ask=price + 0.05, volume=10).ok
    # each failure mode is rejected
    assert not validate_tick(0.0).ok                                   # non-positive
    assert not validate_tick(-5.0).ok
    assert not validate_tick(100.0, ts_age_s=60.0, max_age_s=30.0).ok  # stale
    assert not validate_tick(100.0, bid=101.0, ask=100.0).ok           # crossed book
    assert not validate_tick(100.0, bid=-1.0, ask=100.0).ok            # non-positive quote
    assert not validate_tick(200.0, prev_price=100.0, max_jump_pct=0.20).ok  # 100% jump
    assert not validate_tick(100.0, volume=-1).ok                      # negative volume


def test_price_jump_threshold_is_respected_both_sides():
    prev = 100.0
    for max_jump in (0.05, 0.20, 0.50):
        # just inside the band -> ok; just outside -> rejected
        inside = prev * (1 + max_jump * 0.9)
        outside = prev * (1 + max_jump * 1.1)
        assert validate_tick(inside, prev_price=prev, max_jump_pct=max_jump).ok
        assert not validate_tick(outside, prev_price=prev, max_jump_pct=max_jump).ok


# ------------------------------------------------------- instrument metadata
def test_round_to_tick_output_is_always_aligned_and_idempotent():
    for price in (0.07, 1.03, 99.99, 100.0, 2501.27):
        for tick in (0.05, 0.10, 1.00):
            r = round_to_tick(price, tick)
            assert tick_aligned(r, tick), (price, tick, r)
            assert abs(round_to_tick(r, tick) - r) < EPS   # idempotent


def test_order_meta_validation_invariants():
    today = dt.date(2026, 6, 17)
    # aligned qty + price, unexpired -> ok
    assert validate_order_against_meta(quantity=50, price=100.05, lot_size=25,
                                       tick_size=0.05, freeze_qty=1800,
                                       expiry=dt.date(2026, 6, 25), today=today).ok
    # qty not a lot multiple -> reject
    assert not validate_order_against_meta(quantity=30, lot_size=25).ok
    # over freeze limit -> reject
    assert not validate_order_against_meta(quantity=2000, lot_size=25, freeze_qty=1800).ok
    # price off tick -> reject
    assert not validate_order_against_meta(quantity=25, price=100.03, lot_size=25,
                                           tick_size=0.05).ok
    # expired contract -> reject
    assert not validate_order_against_meta(quantity=25, lot_size=25,
                                           expiry=dt.date(2026, 6, 10), today=today).ok
    # non-positive qty -> reject
    assert not validate_order_against_meta(quantity=0).ok
    # missing metadata never blocks (can't validate what we don't have)
    assert validate_order_against_meta(quantity=7).ok


# ------------------------------------------------------- policy gate invariants
def test_exit_product_support_matches_whitelist():
    candidates = itertools.product(
        ("NSE", "BSE", "NFO", "MCX", "CDS", None),
        ("MIS", "CNC", "NRML", "BO", None),
    )
    for exch, prod in candidates:
        assert exit_product_supported(exch, prod) == ((exch, prod) in SUPPORTED_EXIT_PRODUCTS)


def test_live_structures_always_blocked_paper_never():
    for enabled in (True, False):
        assert live_structures_block_reason("paper", enabled) is None
        assert live_structures_block_reason("sim", enabled) is None
        # live is fail-closed today regardless of the flag (no live basket lifecycle)
        assert live_structures_block_reason("live", enabled) is not None


def test_entry_meta_gate_only_applies_to_live():
    bad = dict(quantity=30, price=100.03, order_type="LIMIT",
               inst={"lot_size": 25, "tick_size": 0.05})
    # sim / paper are never gated, even with malformed metadata
    assert entry_meta_block_reason("paper", **bad) is None
    assert entry_meta_block_reason("sim", **bad) is None
    # live with the same malformed order is blocked
    assert entry_meta_block_reason("live", **bad) is not None
    # live with a clean order passes
    assert entry_meta_block_reason("live", quantity=25, price=100.05, order_type="LIMIT",
                                   inst={"lot_size": 25, "tick_size": 0.05}) is None


def test_close_books_fully_only_on_complete_and_full_fill():
    for status in ("COMPLETE", "PARTIAL", "REJECTED", "UNKNOWN"):
        for filled, pos in itertools.product((0, 25, 50), (25, 50)):
            expected = status == "COMPLETE" and filled >= pos
            assert close_books_fully(status, filled, pos) is expected, (status, filled, pos)
