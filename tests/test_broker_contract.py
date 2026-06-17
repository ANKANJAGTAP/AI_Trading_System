"""#37 — broker contract tests.

These pin down the behaviour ANY broker adapter (the `MockBroker` sim today, the
real `KiteAdapter` live) must satisfy, by driving the deterministic mock through
every order-lifecycle scenario and asserting the system's own fill-truth and
lifecycle helpers reach the *safe* conclusion. The cardinal rule under test:
**only a fully-COMPLETE broker fill books clean P&L — partial / unknown / rejected
/ cancelled-after-partial must never fabricate a close.**

All DB-free and SDK-free: the mock has no `kiteconnect` import, no network, no DB.
"""
from __future__ import annotations

import pytest

from broker.base import BrokerAdapter
from broker.mock_broker import (CANCELLED, COMPLETE, OPEN, REJECTED, SCENARIOS,
                                MockBroker)
from execution.order_lifecycle import (PROTECTED, RECONCILE_REQUIRED,
                                       UNPROTECTED, entry_outcome)
from execution.policy import (close_books_fully, duplicate_exit_risk,
                              normalize_exit_status, reduce_order_history)


def _poll(mb: MockBroker, oid: str, times: int = 1) -> dict:
    """Read the broker `times` times (as the executor's poll loop would); return
    the latest state."""
    last: dict = {}
    for _ in range(times):
        last = mb.order_history(oid)[-1]
    return last


def _norm(state: dict) -> str:
    return normalize_exit_status(state["status"], state["filled_quantity"])


# ----------------------------------------------------- interface compliance
def test_mock_implements_full_broker_interface():
    """Instantiating proves every abstractmethod is implemented; we also check the
    mock covers each name the ABC declares."""
    iface = set(BrokerAdapter.__abstractmethods__)
    assert iface, "BrokerAdapter should declare abstract methods"
    mb = MockBroker()
    assert isinstance(mb, BrokerAdapter)
    assert MockBroker.__abstractmethods__ == frozenset()
    for name in iface:
        assert callable(getattr(mb, name)), f"mock missing interface method {name}"
    # de-facto read surface the executor / reconciler / recovery rely on:
    for name in ("order_history", "orders", "quote", "ltp", "gtts"):
        assert callable(getattr(mb, name)), name


def test_real_kite_adapter_satisfies_interface_when_sdk_present():
    """In CI (kiteconnect installed) this verifies the real adapter implements the
    same contract; in the bare sandbox it skips."""
    pytest.importorskip("kiteconnect")
    from broker.kite_adapter import KiteAdapter
    assert KiteAdapter.__abstractmethods__ == frozenset()
    for name in ("order_history", "orders", "quote", "ltp", "gtts"):
        assert callable(getattr(KiteAdapter, name, None)), name


# ----------------------------------------------------- exit fill-truth
def test_complete_exit_books_fully():
    mb = MockBroker(default_scenario="complete")
    oid = mb.place_order(tradingsymbol="INFY", exchange="NSE",
                         transaction_type="SELL", quantity=75, order_type="MARKET")
    st = _poll(mb, oid)
    assert st["status"] == COMPLETE and st["filled_quantity"] == 75
    assert _norm(st) == "COMPLETE"
    assert close_books_fully(_norm(st), st["filled_quantity"], 75) is True


def test_partial_stuck_exit_does_not_book():
    mb = MockBroker(default_scenario="partial_then_stuck")
    oid = mb.place_order(tradingsymbol="INFY", exchange="NSE",
                         transaction_type="SELL", quantity=100, order_type="MARKET")
    st = _poll(mb, oid, times=3)            # stays part-filled no matter how often we poll
    assert st["status"] == OPEN and 0 < st["filled_quantity"] < 100
    assert _norm(st) == "PARTIAL"
    assert close_books_fully(_norm(st), st["filled_quantity"], 100) is False


def test_rejected_exit_does_not_book():
    mb = MockBroker(default_scenario="rejected")
    oid = mb.place_order(tradingsymbol="INFY", exchange="NSE",
                         transaction_type="SELL", quantity=50, order_type="MARKET")
    st = _poll(mb, oid)
    assert st["status"] == REJECTED and st["filled_quantity"] == 0
    assert _norm(st) == "REJECTED"
    assert close_books_fully(_norm(st), 0, 50) is False


def test_no_fill_exit_is_unknown_not_booked():
    mb = MockBroker(default_scenario="no_fill")
    oid = mb.place_order(tradingsymbol="INFY", exchange="NSE",
                         transaction_type="SELL", quantity=50, order_type="MARKET")
    st = _poll(mb, oid, times=2)
    assert st["status"] == OPEN and st["filled_quantity"] == 0
    assert _norm(st) == "UNKNOWN"
    assert close_books_fully(_norm(st), 0, 50) is False


def test_partial_then_complete_books_only_at_the_end():
    mb = MockBroker(default_scenario="partial_then_complete")
    oid = mb.place_order(tradingsymbol="INFY", exchange="NSE",
                         transaction_type="SELL", quantity=100, order_type="MARKET")
    first = mb.order_history(oid)[-1]       # poll 1 -> partial
    assert _norm(first) == "PARTIAL"
    assert close_books_fully(_norm(first), first["filled_quantity"], 100) is False
    second = mb.order_history(oid)[-1]      # poll 2 -> complete
    assert _norm(second) == "COMPLETE" and second["filled_quantity"] == 100
    assert close_books_fully(_norm(second), 100, 100) is True


def test_cancel_after_partial_keeps_fill_and_does_not_book():
    """The dangerous case: a part-filled exit we cancel. The broker keeps the
    filled qty, the status is terminal CANCELLED, and we must NOT book a clean
    close — it goes to reconcile/pending."""
    mb = MockBroker(default_scenario="partial_then_stuck")
    oid = mb.place_order(tradingsymbol="INFY", exchange="NSE",
                         transaction_type="SELL", quantity=100, order_type="MARKET")
    part = _poll(mb, oid)
    filled = part["filled_quantity"]
    assert 0 < filled < 100
    mb.cancel_order(oid)
    st = mb.latest(oid)
    assert st["status"] == CANCELLED and st["filled_quantity"] == filled
    assert _norm(st) == "REJECTED"          # terminal cancel -> not a clean fill
    assert close_books_fully(_norm(st), filled, 100) is False


# ----------------------------------------------------- entry lifecycle
def test_entry_outcomes_across_scenarios():
    mb = MockBroker()
    # clean full fill, bracketed -> PROTECTED
    oid = mb.place_order(tradingsymbol="INFY", exchange="NSE", transaction_type="BUY",
                         quantity=50, order_type="MARKET", scenario="complete")
    f = _poll(mb, oid)["filled_quantity"]
    assert entry_outcome(f, 50, remainder_dealt_with=True, bracket_ok=True) == PROTECTED
    # full fill but no protective bracket -> UNPROTECTED
    assert entry_outcome(f, 50, remainder_dealt_with=True, bracket_ok=False) == UNPROTECTED
    # part-filled, remainder cancel CONFIRMED, bracket on the filled qty -> PROTECTED
    oid2 = mb.place_order(tradingsymbol="TCS", exchange="NSE", transaction_type="BUY",
                          quantity=100, order_type="LIMIT", scenario="partial_then_stuck")
    pf = _poll(mb, oid2)["filled_quantity"]
    mb.cancel_order(oid2)
    assert entry_outcome(pf, 100, remainder_dealt_with=True, bracket_ok=True) == PROTECTED
    # part-filled but remainder NOT confirmed -> RECONCILE_REQUIRED
    assert entry_outcome(pf, 100, remainder_dealt_with=False, bracket_ok=True) == RECONCILE_REQUIRED
    # nothing filled, remainder confirmed dead -> clean REJECTED
    oid3 = mb.place_order(tradingsymbol="WIPRO", exchange="NSE", transaction_type="BUY",
                          quantity=50, order_type="LIMIT", scenario="no_fill")
    nf = _poll(mb, oid3)["filled_quantity"]
    mb.cancel_order(oid3)
    assert entry_outcome(nf, 50, remainder_dealt_with=True, bracket_ok=False) == "REJECTED"


# ----------------------------------------------------- positions / duplicate-exit
def test_duplicate_exit_guard_from_broker_net_quantity():
    mb = MockBroker(default_scenario="complete")
    buy = mb.place_order(tradingsymbol="INFY", exchange="NSE", transaction_type="BUY",
                         quantity=75, order_type="MARKET")
    _poll(mb, buy)
    assert mb.net_quantity("INFY") == 75
    assert duplicate_exit_risk(mb.net_quantity("INFY")) is False   # still long -> exit is real
    sell = mb.place_order(tradingsymbol="INFY", exchange="NSE", transaction_type="SELL",
                          quantity=75, order_type="MARKET")
    _poll(mb, sell)
    assert mb.net_quantity("INFY") == 0
    assert duplicate_exit_risk(mb.net_quantity("INFY")) is True    # flat -> don't double-fire
    # broker truth is reflected in positions()
    net = {p["tradingsymbol"]: p["quantity"] for p in mb.positions()["net"]}
    assert net["INFY"] == 0


# ----------------------------------------------------- order plumbing
def test_place_order_ids_unique_and_tracked():
    mb = MockBroker()
    ids = {mb.place_order(tradingsymbol="X", exchange="NSE",
                          transaction_type="BUY", quantity=1) for _ in range(5)}
    assert len(ids) == 5
    assert len(mb.orders()) == 5


def test_unknown_scenario_rejected():
    mb = MockBroker()
    with pytest.raises(ValueError):
        mb.place_order(tradingsymbol="X", exchange="NSE", transaction_type="BUY",
                       quantity=1, scenario="teleport")
    with pytest.raises(ValueError):
        MockBroker(default_scenario="nope")


def test_gtt_oco_lifecycle():
    mb = MockBroker()
    tid = mb.place_oco(tradingsymbol="INFY", exchange="NSE", last_price=100.0,
                       lower_trigger=95.0, upper_trigger=110.0, orders=[])
    assert any(g["id"] == tid for g in mb.gtts())
    mb.delete_gtt(tid)
    assert all(g["id"] != tid for g in mb.gtts())


def test_scenarios_constant_matches_engine():
    assert SCENARIOS == {"complete", "partial_then_complete", "partial_then_stuck",
                         "rejected", "no_fill"}


# ----------------------------------------------------- full reduction chain
# These exercise the exact pure reduction the live executor uses (_poll_order ->
# policy.reduce_order_history), end to end against the broker sim.
def test_reduce_order_history_matches_broker_truth():
    mb = MockBroker(default_scenario="complete")
    oid = mb.place_order(tradingsymbol="INFY", exchange="NSE",
                         transaction_type="SELL", quantity=75, order_type="MARKET")
    rec = reduce_order_history(mb.order_history(oid))
    assert rec["terminal"] is True and rec["status"] == COMPLETE and rec["filled"] == 75
    # empty / missing history -> safe non-terminal record (keep polling, never crash)
    empty = reduce_order_history([])
    assert empty["status"] is None and empty["filled"] == 0 and empty["terminal"] is False


def test_full_chain_history_to_booking_decision():
    """broker order_history -> reduce -> normalize -> close_books_fully, for every
    scenario, mirroring the executor's poll loop."""
    expected = {
        "complete": ("COMPLETE", True),
        "partial_then_stuck": ("PARTIAL", False),
        "rejected": ("REJECTED", False),
        "no_fill": ("UNKNOWN", False),
    }
    for scenario, (exp_norm, exp_book) in expected.items():
        mb = MockBroker(default_scenario=scenario)
        oid = mb.place_order(tradingsymbol="INFY", exchange="NSE",
                             transaction_type="SELL", quantity=100, order_type="MARKET")
        rec: dict = {"terminal": False, "status": None, "filled": 0}
        for _ in range(3):                      # the executor polls until terminal
            rec = reduce_order_history(mb.order_history(oid))
            if rec["terminal"]:
                break
        norm = normalize_exit_status(rec["status"], rec["filled"])
        assert norm == exp_norm, (scenario, norm)
        assert close_books_fully(norm, rec["filled"], 100) is exp_book, scenario
