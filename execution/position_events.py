"""Event-sourced position state (#17) — pure reducer, no I/O.

`position_events` (migration 0017) is an append-only, immutable log per position:
`entry | partial_close | full_close | close_pending`, each row carrying the broker
fill truth (filled_qty, avg_price, pending_qty, status). This rebuilds the current
position state purely from that history, so it can be diffed against the mutable
`positions` row to catch drift (the basis for an audit / rebuild).
"""
from __future__ import annotations

ENTRY = "entry"
PARTIAL_CLOSE = "partial_close"
FULL_CLOSE = "full_close"
CLOSE_PENDING = "close_pending"


def _ordered(events: list[dict]) -> list[dict]:
    return sorted(events, key=lambda e: (str(e.get("ts") or ""), int(e.get("id") or 0)))


def position_from_events(events: list[dict]) -> dict:
    """Reduce an event log (any order) to current state:
    {opened_qty, closed_qty, net_qty, status, pending_qty, realized_pnl, events}.
    status: open | closed | close_pending | unknown."""
    evs = _ordered(events)
    opened = closed = pending = 0
    realized = 0.0
    for e in evs:
        et = e.get("event_type")
        fq = int(e.get("filled_qty") or 0)
        pending = int(e.get("pending_qty") or 0)          # latest wins
        realized += float((e.get("detail") or {}).get("realized_pnl") or 0.0)
        if et == ENTRY:
            opened += fq
        elif et in (PARTIAL_CLOSE, FULL_CLOSE):
            closed += fq
    net = opened - closed
    last_type = evs[-1].get("event_type") if evs else None
    if last_type == CLOSE_PENDING:
        status = "close_pending"
    elif closed > 0 and net <= 0:
        status = "closed"
    elif opened > 0:
        status = "open"
    else:
        status = "unknown"
    return {
        "opened_qty": opened, "closed_qty": closed, "net_qty": max(0, net),
        "status": status, "pending_qty": pending, "realized_pnl": round(realized, 2),
        "events": len(evs),
    }


def reconcile_position(events: list[dict], stored_qty: int, stored_status: str) -> dict:
    """Compare the event-derived state to the stored positions-row values. Returns
    {match, drift} — a non-empty drift means the mutable row disagrees with the
    immutable log (investigate before trusting the position)."""
    derived = position_from_events(events)
    drift = {}
    if int(stored_qty or 0) != derived["net_qty"]:
        drift["quantity"] = {"stored": int(stored_qty or 0), "derived": derived["net_qty"]}
    if stored_status and stored_status != derived["status"]:
        drift["status"] = {"stored": stored_status, "derived": derived["status"]}
    return {"match": not drift, "drift": drift, "derived": derived}
