"""Durable cross-process command queue (API -> engine), DB-backed (P1#12).

State-style controls (pause / mode / sleeve toggles / kill-switch reset) go through
config_state. One-shot ACTIONS that must run inside the engine's executor —
flatten-all, close, modify — are persisted in the `commands` table with a state
machine + idempotency + atomic claim, so a flatten/kill SURVIVES an engine crash
and replays on restart (the old fire-and-forget Redis LPOP lost anything popped
but not yet executed).
"""
from __future__ import annotations

import json

from common.db import execute, fetch, fetchrow, fetchval
from common.logging import get_logger

log = get_logger("commands")

CREATED, CLAIMED, EXECUTING, SUCCEEDED, FAILED, RETRYING, DEAD_LETTER = (
    "CREATED", "CLAIMED", "EXECUTING", "SUCCEEDED", "FAILED", "RETRYING", "DEAD_LETTER")
_MAX_ATTEMPTS = 5


def next_state(current: str, event: str, attempts: int = 0, max_attempts: int = _MAX_ATTEMPTS) -> str:
    """Pure command-lifecycle transition (claim / succeed / fail)."""
    if event == "claim" and current in (CREATED, RETRYING):
        return CLAIMED
    if event == "succeed" and current in (CLAIMED, EXECUTING):
        return SUCCEEDED
    if event == "fail" and current in (CLAIMED, EXECUTING):
        return DEAD_LETTER if attempts + 1 >= max_attempts else RETRYING
    return current


async def enqueue_command(command: dict, idempotency_key: str | None = None) -> int | None:
    """Persist a command (CREATED). Idempotent on idempotency_key — a duplicate
    returns the existing id and creates no second row."""
    ctype = command.get("type")
    row = await fetchrow(
        "INSERT INTO commands (idempotency_key, type, payload, status) "
        "VALUES ($1,$2,$3::jsonb,'CREATED') "
        "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id",
        idempotency_key, ctype, json.dumps(command, default=str))
    if row:
        log.info("command_enqueued", type=ctype, id=row["id"])
        return row["id"]
    if idempotency_key:   # conflict: hand back the existing command's id
        existing = await fetchval("SELECT id FROM commands WHERE idempotency_key=$1", idempotency_key)
        return int(existing) if existing is not None else None
    return None


async def claim_commands(worker: str = "engine", max_n: int = 50) -> list[dict]:
    """Atomically claim pending commands (CREATED/RETRYING). Each returned dict is
    the original command payload plus `_id`. FOR UPDATE SKIP LOCKED keeps concurrent
    claimers from racing on the same row."""
    rows = await fetch(
        "UPDATE commands SET status='CLAIMED', claimed_by=$1, updated_at=now() "
        "WHERE id IN (SELECT id FROM commands WHERE status IN ('CREATED','RETRYING') "
        "ORDER BY created_at LIMIT $2 FOR UPDATE SKIP LOCKED) RETURNING id, payload",
        worker, int(max_n))
    out: list[dict] = []
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        out.append({**(payload or {}), "_id": r["id"]})
    return out


async def complete_command(command_id: int) -> None:
    await execute("UPDATE commands SET status='SUCCEEDED', updated_at=now() WHERE id=$1", command_id)


async def fail_command(command_id: int, error: str, max_attempts: int = _MAX_ATTEMPTS) -> None:
    row = await fetchrow("SELECT attempts FROM commands WHERE id=$1", command_id)
    attempts = int(row["attempts"]) if row else 0
    new = next_state(CLAIMED, "fail", attempts, max_attempts)
    await execute(
        "UPDATE commands SET status=$2, attempts=attempts+1, last_error=$3, updated_at=now() WHERE id=$1",
        command_id, new, (error or "")[:500])
    log.warning("command_failed", id=command_id, new_status=new, attempts=attempts + 1)


async def recover_stuck_commands() -> int:
    """Replay-after-restart: reset any CLAIMED/EXECUTING command (a crashed engine
    left it mid-flight) back to RETRYING so it runs again. Returns count recovered."""
    n = await fetchval(
        "WITH u AS (UPDATE commands SET status='RETRYING', updated_at=now() "
        "WHERE status IN ('CLAIMED','EXECUTING') RETURNING 1) SELECT count(*) FROM u")
    return int(n or 0)
