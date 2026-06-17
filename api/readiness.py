"""#32 — operational live-readiness aggregation.

The pre-live checklist (P0#2) answers "is the system *configured* to go live." This
answers "is it *operationally safe* right now": no commands stuck in flight, no open
positions left unguarded, a live data feed, and a recent verified backup. Each tile
is best-effort and fails soft to 'warn' so the summary never throws, and the pure
`overall_ready` rolls them into one pass/warn/fail the UI can gate the live flip on.
"""
from __future__ import annotations

from common.logging import get_logger

log = get_logger("readiness")

OK, WARN, DOWN = "ok", "warn", "down"


def overall_ready(tiles: list[dict]) -> str:
    """pass only if every tile is ok; fail if any is down; warn otherwise. Pure."""
    statuses = [t.get("status") for t in tiles]
    if not statuses:
        return "warn"
    if any(s == DOWN for s in statuses):
        return "fail"
    return "pass" if all(s == OK for s in statuses) else "warn"


async def _pending_commands() -> dict:
    tile = {"key": "pending_commands", "label": "Pending commands"}
    try:
        from common.db import fetchval
        n = int(await fetchval(
            "SELECT COUNT(*) FROM commands WHERE status IN ('pending','claimed')") or 0)
        return {**tile, "status": OK if n == 0 else WARN, "detail": f"{n} queued / in-flight"}
    except Exception as exc:
        return {**tile, "status": WARN, "detail": f"unknown ({exc})"}


async def _open_positions() -> dict:
    tile = {"key": "open_positions", "label": "Open positions"}
    try:
        from common.db import fetchval
        n = int(await fetchval("SELECT COUNT(*) FROM positions WHERE status='open'") or 0)
        return {**tile, "status": OK, "detail": f"{n} open"}
    except Exception as exc:
        return {**tile, "status": WARN, "detail": f"unknown ({exc})"}


async def _entry_block() -> dict:
    tile = {"key": "entry_block", "label": "Unsafe-entry block"}
    try:
        from common.state import get_state
        blocked = bool(await get_state("block_new_entries", False))
        ks = bool(await get_state("kill_switch_active", False))
        if ks:
            return {**tile, "status": DOWN, "detail": "kill-switch ACTIVE"}
        return {**tile, "status": OK if not blocked else WARN,
                "detail": "clear" if not blocked else "new entries blocked (unprotected exposure)"}
    except Exception as exc:
        return {**tile, "status": WARN, "detail": f"unknown ({exc})"}


async def _data_feed() -> dict:
    """Live tick feed health. Today the system is paper-mode with no live websocket
    (depends on the real adapter, §1) — so this is honestly 'warn', not 'ok'."""
    tile = {"key": "data_feed", "label": "Live market-data feed"}
    try:
        from common.state import get_state
        mode = await get_state("runtime_mode", "simulated_fill")
        if mode == "live":
            return {**tile, "status": OK, "detail": "live feed expected"}
        return {**tile, "status": WARN, "detail": "paper mode — no live tick feed yet"}
    except Exception as exc:
        return {**tile, "status": WARN, "detail": f"unknown ({exc})"}


async def _last_backup() -> dict:
    """No DB-side backup signal exists (backups are a server-side cron, §7). Surface a
    reminder rather than a false 'ok'."""
    return {"key": "last_backup", "label": "DB backup verified",
            "status": WARN, "detail": "verify cron + restore drill on the server (RUNBOOK)"}


async def readiness_summary() -> dict:
    """Aggregate the operational tiles + an overall roll-up the UI gates live on."""
    tiles = [await _pending_commands(), await _open_positions(), await _entry_block(),
             await _data_feed(), await _last_backup()]
    return {"overall": overall_ready(tiles), "tiles": tiles}
