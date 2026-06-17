"""First-class broker reconciliation (P1#11).

Promotes the slow-loop position reconcile into a graded check: compare the
broker's net positions against the local book, classify the severity, ACT on it
(block new entries + alert — the operator flattens), and persist a snapshot for
the audit trail. Live-only; paper has no broker truth to reconcile against.
"""
from __future__ import annotations

import json

from common.db import execute
from common.logging import get_logger
from common.state import set_state

log = get_logger("reconciler")

INFO, TRADING_BLOCKED, FLATTEN_REQUIRED, MANUAL = (
    "info", "trading_blocked", "flatten_required", "manual")


def classify_severity(mismatches: list[dict]) -> str:
    """Severity of a position book-vs-broker diff (pure).
    - none                                                  -> info
    - broker holds qty the book doesn't know (book 0, broker != 0)
      -> flatten_required (unprotected live exposure)
    - any other qty mismatch                                -> trading_blocked
    """
    if not mismatches:
        return INFO
    if any(int(m.get("book_qty", 0)) == 0 and int(m.get("broker_qty", 0)) != 0
           for m in mismatches):
        return FLATTEN_REQUIRED
    return TRADING_BLOCKED


async def _persist(severity: str, mismatches: list[dict]) -> None:
    try:
        await execute(
            "INSERT INTO reconciliation_snapshots (severity, findings) VALUES ($1,$2::jsonb)",
            severity, json.dumps({"position_mismatches": mismatches}))
    except Exception as exc:
        log.warning("reconciliation_persist_failed", error=str(exc))


async def run_reconcile(executor, broker_net: list[dict], persist: bool = True) -> str:
    """Reconcile positions vs the broker, classify, act (block + alert), persist.
    Returns the severity. The operator does the actual flatten — we don't auto-
    liquidate a possibly-legitimate manual position."""
    mismatches = await executor.book.reconcile(broker_net, "live")
    severity = classify_severity(mismatches)
    if severity in (TRADING_BLOCKED, FLATTEN_REQUIRED):
        await set_state("block_new_entries", True, "reconcile")
        msg = (f"Reconciliation {severity}: {len(mismatches)} book/broker mismatch(es). "
               f"New entries blocked. {mismatches}")
        log.error("reconciliation_action", severity=severity, mismatches=mismatches)
        if getattr(executor, "alerter", None):
            try:
                await executor.alerter.send_async(f"Reconciliation {severity}", msg)
            except Exception:
                pass
    if persist:
        await _persist(severity, mismatches)
    return severity
