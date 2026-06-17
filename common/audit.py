"""Immutable audit trail + signal/gate persistence (spec §9).

Every signal, gate result, sizing calc, LLM verdict, order, and error is written
with a correlation_id so any trade can be fully reconstructed. audit_log is the
append-only event stream; signals + gate_results capture the decision trail.
"""
from __future__ import annotations

import json
import uuid

from common.db import execute, fetch, fetchrow


def new_correlation_id() -> str:
    return str(uuid.uuid4())


async def audit(event_type: str, component: str, message: str = "",
                correlation_id: str | None = None, payload: dict | None = None) -> None:
    await execute(
        "INSERT INTO audit_log (correlation_id, event_type, component, message, payload) "
        "VALUES ($1, $2, $3, $4, $5::jsonb)",
        uuid.UUID(correlation_id) if correlation_id else None,
        event_type, component, message, json.dumps(payload or {}),
    )


async def compute_and_store_daily_digest(trade_date) -> str:
    """#18: fold a day's audit_log rows into a tamper-evident sha256 hash-chain,
    chained to the prior day's digest, and upsert into audit_digests. Returns the
    digest. Meant to run once daily (NOT on the audit write path)."""
    from common.audit_chain import chain_digest
    rows = await fetch(
        "SELECT id, ts, event_type, component, message, payload FROM audit_log "
        "WHERE ts::date = $1 ORDER BY ts, id", trade_date)
    prev = await fetchrow(
        "SELECT digest FROM audit_digests WHERE trade_date < $1 "
        "ORDER BY trade_date DESC LIMIT 1", trade_date)
    prev_digest = prev["digest"] if prev else None
    items = [{"id": r["id"], "ts": r["ts"].isoformat(), "event_type": r["event_type"],
              "component": r["component"], "message": r["message"], "payload": r["payload"]}
             for r in rows]
    digest, n = chain_digest(items, prev_digest)
    await execute(
        "INSERT INTO audit_digests (trade_date, row_count, digest, prev_digest) "
        "VALUES ($1, $2, $3, $4) ON CONFLICT (trade_date) DO UPDATE SET "
        "row_count = EXCLUDED.row_count, digest = EXCLUDED.digest, "
        "prev_digest = EXCLUDED.prev_digest, created_at = now()",
        trade_date, n, digest, prev_digest)
    return digest


async def persist_signal(sleeve: str, instrument: dict, decision: str, confidence: float,
                         reason: str | None, correlation_id: str, signal=None,
                         features: dict | None = None) -> int:
    row = await fetchrow(
        "INSERT INTO signals (correlation_id, sleeve, instrument_token, tradingsymbol, setup, side, "
        "entry_price, stop_price, target_price, confidence, decision, reason, raw, features) "
        "VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,$14::jsonb) RETURNING id",
        correlation_id, sleeve, instrument.get("instrument_token"), instrument.get("tradingsymbol"),
        getattr(signal, "setup", None), getattr(signal, "side", None),
        getattr(signal, "entry", None), getattr(signal, "stop", None), getattr(signal, "target", None),
        confidence, decision, reason,
        json.dumps(getattr(signal, "detail", {}) if signal else {}),
        json.dumps(features or {}),
    )
    return row["id"]


async def persist_gates(signal_id: int, correlation_id: str, gates) -> None:
    for g in gates:
        await execute(
            "INSERT INTO gate_results (signal_id, correlation_id, gate_name, passed, score, detail) "
            "VALUES ($1, $2::uuid, $3, $4, $5, $6::jsonb)",
            signal_id, correlation_id, g.name, g.passed, g.score, json.dumps(g.detail),
        )
