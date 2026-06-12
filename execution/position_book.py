"""Position book (spec §8): durable in Postgres (`positions`) + live state in Redis.
Reconciles against the broker each cycle and alerts on mismatch.
"""
from __future__ import annotations

import json

from common.db import execute, fetch, fetchrow
from common.logging import get_logger
from common.redis_client import get_redis

log = get_logger("position_book")
_OPEN_SET = "positions:open"


class PositionBook:
    def __init__(self, alerter=None) -> None:
        self.alerter = alerter

    async def open_position(self, decision, fill, mode: str) -> int:
        row = await fetchrow(
            "INSERT INTO positions (correlation_id, mode, sleeve, instrument_token, tradingsymbol, "
            "side, quantity, average_price, entry_price, stop_price, target_price, r_rupees, status, raw) "
            "VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'open',$13::jsonb) RETURNING id",
            decision.correlation_id, mode, decision.sleeve,
            decision.instrument.get("instrument_token"), decision.instrument.get("tradingsymbol"),
            decision.side, fill.quantity, fill.price, fill.price,
            decision.stop_price, decision.target_price, decision.r_rupees,
            json.dumps({"entry_fees": fill.fees}),
        )
        pid = row["id"]
        r = await get_redis()
        await r.hset(f"pos:{pid}", mapping={
            "instrument_token": str(decision.instrument.get("instrument_token")),
            "tradingsymbol": decision.instrument.get("tradingsymbol") or "",
            "side": decision.side, "quantity": str(fill.quantity), "entry": str(fill.price),
            "stop": str(decision.stop_price), "target": str(decision.target_price),
            "sleeve": decision.sleeve, "mode": mode,
        })
        await r.sadd(_OPEN_SET, str(pid))
        log.info("position_opened", id=pid, symbol=decision.instrument.get("tradingsymbol"),
                 qty=fill.quantity, price=fill.price, mode=mode)
        return pid

    async def adopt_row(self, broker_pos: dict, side: str, qty: int, entry: float,
                        stop: float | None, target: float | None, mode: str, status: str) -> int:
        """Upsert an adopted (cold-start) live position reconstructed from the broker."""
        tok = broker_pos.get("instrument_token")
        existing = await fetchrow(
            "SELECT id FROM positions WHERE instrument_token=$1 AND mode=$2 "
            "AND status IN ('open','flagged') LIMIT 1", tok, mode)
        if existing:
            await execute(
                "UPDATE positions SET quantity=$2, average_price=$3, entry_price=$3, stop_price=$4, "
                "target_price=$5, side=$6, status=$7 WHERE id=$1",
                existing["id"], qty, entry, stop, target, side, status)
            return existing["id"]
        row = await fetchrow(
            "INSERT INTO positions (correlation_id, mode, sleeve, instrument_token, tradingsymbol, "
            "side, quantity, average_price, entry_price, stop_price, target_price, status, raw) "
            "VALUES (gen_random_uuid(),$1,'adopted',$2,$3,$4,$5,$6,$6,$7,$8,$9,$10::jsonb) RETURNING id",
            mode, tok, broker_pos.get("tradingsymbol"), side, qty, entry, stop, target, status,
            json.dumps({"adopted": True}))
        return row["id"]

    async def attach_bracket(self, pid: int, bracket: dict) -> None:
        """Persist the live bracket (incl. gtt_id) onto the position so close() can
        cancel the resting GTT-OCO instead of leaving it to re-fire."""
        await execute("UPDATE positions SET raw = COALESCE(raw,'{}'::jsonb) || $2::jsonb WHERE id=$1",
                      pid, json.dumps({"bracket": bracket}))

    async def persist_order_fill(self, decision, fill, mode: str, status: str,
                                 broker_order_id: str | None = None) -> int | None:
        """Append the order + fill rows (the §9 order/fill audit trail). Best-effort:
        a persistence failure must not abort the trade."""
        try:
            inst = decision.instrument or {}
            row = await fetchrow(
                "INSERT INTO orders (correlation_id, signal_id, broker_order_id, mode, sleeve, "
                "instrument_token, tradingsymbol, side, order_type, product, quantity, "
                "filled_quantity, price, status) "
                "VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) RETURNING id",
                decision.correlation_id, decision.signal_id, broker_order_id, mode, decision.sleeve,
                inst.get("instrument_token"), inst.get("tradingsymbol"), decision.side,
                decision.order_type, decision.product, decision.quantity,
                fill.quantity, fill.price, status)
            oid = row["id"]
            await execute(
                "INSERT INTO fills (order_id, correlation_id, broker_order_id, instrument_token, "
                "tradingsymbol, side, quantity, price, fees, mode) "
                "VALUES ($1,$2::uuid,$3,$4,$5,$6,$7,$8,$9::jsonb,$10)",
                oid, decision.correlation_id, broker_order_id, inst.get("instrument_token"),
                inst.get("tradingsymbol"), decision.side, fill.quantity, fill.price,
                json.dumps(fill.fees), mode)
            return oid
        except Exception as exc:
            log.warning("order_fill_persist_failed", error=str(exc))
            return None

    async def touch_ltp(self, pid: int, ltp: float) -> None:
        """Cheap per-tick LTP update (Redis only) — no DB write. The durable
        unrealized P&L is flushed on a throttle via update_unrealized()."""
        r = await get_redis()
        await r.hset(f"pos:{pid}", mapping={"ltp": str(ltp)})

    async def update_unrealized(self, pid: int, ltp: float) -> float:
        pos = await fetchrow(
            "SELECT side, quantity, average_price FROM positions WHERE id=$1 AND status='open'", pid)
        if not pos:
            return 0.0
        qty, entry = int(pos["quantity"]), float(pos["average_price"])
        unreal = (ltp - entry) * qty if pos["side"] == "BUY" else (entry - ltp) * qty
        # track MAE/MFE (worst/best unrealized seen while open) for the dashboard
        await execute("UPDATE positions SET unrealized_pnl=$2, mfe=GREATEST(COALESCE(mfe,0),$2), "
                      "mae=LEAST(COALESCE(mae,0),$2) WHERE id=$1", pid, round(unreal, 2))
        r = await get_redis()
        await r.hset(f"pos:{pid}", mapping={"ltp": str(ltp), "unrealized": str(round(unreal, 2))})
        return unreal

    async def close_position(self, pid: int, exit_price: float, exit_fees: dict, reason: str) -> float | None:
        pos = await fetchrow("SELECT * FROM positions WHERE id=$1", pid)
        if not pos or pos["status"] != "open":
            return None
        qty, entry, side = int(pos["quantity"]), float(pos["average_price"]), pos["side"]
        gross = (exit_price - entry) * qty if side == "BUY" else (entry - exit_price) * qty
        raw = pos["raw"] or {}
        if isinstance(raw, str):
            raw = json.loads(raw)
        entry_fees = float((raw.get("entry_fees") or {}).get("total", 0))
        exit_fees_total = float((exit_fees or {}).get("total", 0))
        realized = round(gross - entry_fees - exit_fees_total, 2)
        await execute(
            "UPDATE positions SET status='closed', closed_at=now(), realized_pnl=$2, "
            "unrealized_pnl=0, raw = COALESCE(raw,'{}'::jsonb) || $3::jsonb WHERE id=$1",
            pid, realized,
            json.dumps({"exit_price": exit_price, "exit_fees": exit_fees,
                        "exit_reason": reason, "gross_pnl": round(gross, 2)}),
        )
        r = await get_redis()
        await r.srem(_OPEN_SET, str(pid))
        await r.delete(f"pos:{pid}")
        log.info("position_closed", id=pid, realized=realized, reason=reason)
        return realized

    async def get_open(self, mode: str | None = None) -> list[dict]:
        if mode:
            rows = await fetch("SELECT * FROM positions WHERE status='open' AND mode=$1", mode)
        else:
            rows = await fetch("SELECT * FROM positions WHERE status='open'")
        return [dict(r) for r in rows]

    async def reconcile(self, broker_net_positions: list[dict], mode: str = "live") -> list[dict]:
        """Compare our open book vs broker net positions; return + alert on mismatches."""
        ours: dict = {}
        for p in await self.get_open(mode):
            signed = int(p["quantity"]) * (1 if p["side"] == "BUY" else -1)
            ours[p["instrument_token"]] = ours.get(p["instrument_token"], 0) + signed
        theirs: dict = {}
        for bp in (broker_net_positions or []):
            theirs[bp.get("instrument_token")] = theirs.get(bp.get("instrument_token"), 0) + int(bp.get("quantity", 0))
        mismatches = [
            {"instrument_token": tok, "book_qty": ours.get(tok, 0), "broker_qty": theirs.get(tok, 0)}
            for tok in set(ours) | set(theirs)
            if ours.get(tok, 0) != theirs.get(tok, 0)
        ]
        if mismatches:
            log.error("position_reconciliation_mismatch", count=len(mismatches), detail=mismatches)
            if self.alerter:
                await self.alerter.send_async("Position reconciliation mismatch",
                                              f"{len(mismatches)} mismatch(es): {mismatches}")
        return mismatches
