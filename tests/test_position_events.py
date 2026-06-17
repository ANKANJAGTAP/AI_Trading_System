"""#17 — event-sourced position reducer + reconciliation."""
from execution.position_events import position_from_events, reconcile_position


def test_open_then_full_close():
    evs = [
        {"id": 1, "event_type": "entry", "filled_qty": 100, "avg_price": 50.0, "ts": "t1"},
        {"id": 2, "event_type": "full_close", "filled_qty": 100, "avg_price": 55.0, "ts": "t2",
         "detail": {"realized_pnl": 500.0}},
    ]
    s = position_from_events(evs)
    assert s["net_qty"] == 0 and s["status"] == "closed"
    assert s["opened_qty"] == 100 and s["closed_qty"] == 100 and s["realized_pnl"] == 500.0


def test_partial_close_leaves_position_open():
    evs = [
        {"id": 1, "event_type": "entry", "filled_qty": 100, "ts": "t1"},
        {"id": 2, "event_type": "partial_close", "filled_qty": 40, "ts": "t2",
         "detail": {"realized_pnl": 120.0}},
    ]
    s = position_from_events(evs)
    assert s["net_qty"] == 60 and s["status"] == "open" and s["realized_pnl"] == 120.0


def test_close_pending_is_terminalish_unconfirmed():
    evs = [
        {"id": 1, "event_type": "entry", "filled_qty": 50, "ts": "t1"},
        {"id": 2, "event_type": "close_pending", "pending_qty": 50, "ts": "t2"},
    ]
    s = position_from_events(evs)
    assert s["status"] == "close_pending" and s["net_qty"] == 50 and s["pending_qty"] == 50


def test_order_independent_reduction():
    evs = [
        {"id": 2, "event_type": "partial_close", "filled_qty": 30, "ts": "t2"},
        {"id": 1, "event_type": "entry", "filled_qty": 100, "ts": "t1"},
    ]
    assert position_from_events(evs)["net_qty"] == 70      # sorted by ts/id internally


def test_empty_log_is_unknown():
    s = position_from_events([])
    assert s["status"] == "unknown" and s["net_qty"] == 0 and s["events"] == 0


def test_reconcile_detects_quantity_drift():
    evs = [{"id": 1, "event_type": "entry", "filled_qty": 100, "ts": "t1"}]
    ok = reconcile_position(evs, stored_qty=100, stored_status="open")
    assert ok["match"] is True and ok["drift"] == {}
    bad = reconcile_position(evs, stored_qty=75, stored_status="open")
    assert bad["match"] is False and bad["drift"]["quantity"] == {"stored": 75, "derived": 100}


def test_reconcile_detects_status_drift():
    evs = [
        {"id": 1, "event_type": "entry", "filled_qty": 100, "ts": "t1"},
        {"id": 2, "event_type": "full_close", "filled_qty": 100, "ts": "t2"},
    ]
    out = reconcile_position(evs, stored_qty=0, stored_status="open")
    assert out["match"] is False and out["drift"]["status"]["derived"] == "closed"
