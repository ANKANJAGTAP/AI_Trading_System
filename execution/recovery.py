"""Cold-start / crash recovery (spec §8). The broker is the source of truth.

On restart: adopt open positions + pending protective GTTs, rebuild each position's
R-state (entry/qty/stop/target), re-arm the fast-loop guards, and reconcile to
Postgres. Any position that can't be safely reconstructed (e.g. no protective stop)
is FLAGGED for the operator rather than left unmanaged. Never resume trading with
unmanaged live exposure.
"""
from __future__ import annotations

from common.logging import get_logger
from execution.guards import Guard

log = get_logger("recovery")


def _stops_from_gtts(gtts: list[dict], tradingsymbol: str):
    """Return (lower, upper) trigger values of an OCO GTT for this symbol, else (None, None)."""
    for g in gtts or []:
        cond = g.get("condition") or {}
        tv = sorted(cond.get("trigger_values") or [])
        if cond.get("tradingsymbol") == tradingsymbol and len(tv) == 2:
            return tv[0], tv[1]
    return None, None


async def adopt_open_positions(executor) -> dict:
    mode = executor.mode
    adopted: list[dict] = []
    flagged: list[dict] = []

    if mode == "live":
        try:
            pos = await executor.governor.call("other", executor.adapter.positions)
            net = pos.get("net", []) if isinstance(pos, dict) else []
        except Exception as exc:
            log.error("adopt_failed_positions", error=str(exc))
            return {"adopted": [], "flagged": []}
        try:
            gtts = await executor.governor.call("other", executor.adapter.gtts)
        except Exception:
            gtts = []
        for p in net:
            qty = int(p.get("quantity", 0))
            if qty == 0:
                continue
            sym = p.get("tradingsymbol")
            stop, target = _stops_from_gtts(gtts, sym)
            side = "BUY" if qty > 0 else "SELL"
            entry = float(p.get("average_price") or p.get("last_price") or 0)
            status = "open" if stop is not None else "flagged"
            pid = await executor.book.adopt_row(p, side, abs(qty), entry, stop, target, mode, status)
            if stop is None:
                flagged.append({"id": pid, "tradingsymbol": sym, "reason": "no protective GTT/stop found"})
            else:
                executor.guards.arm(Guard(position_id=pid, side=side, entry=entry,
                                          stop=stop, target=target or 0,
                                          instrument_token=p.get("instrument_token", 0)))
                adopted.append({"id": pid, "tradingsymbol": sym, "qty": abs(qty)})
    else:
        # sim: multi-leg structures first — regroup legs by correlation_id and
        # re-register their combined-P&L guards (a leg has no meaningful per-price
        # stop on its own; the structure is the unit of risk).
        from execution.structures import rebuild_structures
        covered = await rebuild_structures(executor)
        adopted.extend({"id": pid, "structure": True} for pid in covered)
        # then reload the remaining shadow book and re-arm per-price guards
        from execution.brackets import dynamic_exit_cfg
        for p in await executor.book.get_open(mode):
            if p["id"] in covered:
                continue
            if p.get("stop_price") is None:
                flagged.append({"id": p["id"], "reason": "missing stop"})
                continue
            dyn = dynamic_exit_cfg(executor.config, p["sleeve"])
            executor.guards.arm(Guard(
                position_id=p["id"], side=p["side"], entry=float(p["entry_price"]),
                stop=float(p["stop_price"]), target=float(p["target_price"] or 0),
                instrument_token=p.get("instrument_token", 0),
                square_off=executor.square_off_time(p["sleeve"]),
                breakeven_at_r=float(dyn.get("breakeven_at_r", 0) or 0),
                lock_trigger_frac=float(dyn.get("lock_trigger_frac", 0) or 0),
                max_giveback_frac=float(dyn.get("max_giveback_frac", 0.35) or 0.35),
                init_risk=abs(float(p["entry_price"]) - float(p["stop_price"]))))
            adopted.append({"id": p["id"], "tradingsymbol": p["tradingsymbol"], "qty": p["quantity"]})

    if flagged:
        log.warning("cold_start_flagged_for_operator", flagged=flagged)
        if executor.alerter:
            executor.alerter.send("Cold-start: positions need attention", str(flagged))
    log.info("cold_start_adopt_complete", mode=mode, adopted=len(adopted), flagged=len(flagged))
    return {"adopted": adopted, "flagged": flagged}
