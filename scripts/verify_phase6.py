"""Phase 6 acceptance (Monitoring/Dashboard/Alerts/Audit API).

Tests the dashboard data surface in-process (no HTTP/loop issues): REST service
layer shapes, the guarded control route functions (state writes + command enqueue +
go-live token guard), the WebSocket event bus (publish -> subscribe), and full
trade reconstruction from a seeded correlation_id. SELF-CLEANING: resets all shared
state + clears the command queue so the live engine is unaffected. Run with the
engine STOPPED (it mutates shared state transiently).
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid

from fastapi import HTTPException

from api import services
from api.routes import (ConfirmBody, ModeBody, PauseBody, SleeveBody, close_position,
                        control_flatten, control_ks_reset, control_mode, control_pause, control_sleeve)
from common.commands import COMMANDS_KEY
from common.db import close_pool, execute, fetchval, init_pool
from common.events import EVENTS_CHANNEL, publish_event
from common.logging import configure_logging
from common.redis_client import get_redis
from common.state import get_state, set_state

CORR = str(uuid.uuid4())
TOK = 990000111


async def seed():
    sid = await fetchval(
        "INSERT INTO signals (correlation_id, sleeve, instrument_token, tradingsymbol, setup, side, "
        "confidence, decision, reason, raw) VALUES ($1::uuid,'intraday_stocks',$2,'TESTP6','orb','BUY',"
        "0.8,'PASS','seed', $3::jsonb) RETURNING id", CORR, TOK,
        json.dumps({"llm": {"veto": False, "sentiment": "neutral"}}))
    for n, p, s in [("liquidity", True, 1.0), ("regime", True, 0.9), ("confirmation", True, 0.8)]:
        await execute("INSERT INTO gate_results (signal_id, correlation_id, gate_name, passed, score, detail) "
                      "VALUES ($1,$2::uuid,$3,$4,$5,'{}'::jsonb)", sid, CORR, n, p, s)
    for et, comp, msg in [("pipeline_evaluated", "orchestrator", "PASS"), ("risk_sized", "orchestrator", "qty=10"),
                          ("executed", "orchestrator", "FILLED")]:
        await execute("INSERT INTO audit_log (correlation_id, event_type, component, message, payload) "
                      "VALUES ($1::uuid,$2,$3,$4,'{}'::jsonb)", CORR, et, comp, msg)
    # one closed (realized) + one open (unrealized) position today
    await execute("INSERT INTO positions (correlation_id, mode, sleeve, instrument_token, tradingsymbol, side, "
                  "quantity, entry_price, stop_price, target_price, r_rupees, status, realized_pnl) "
                  "VALUES ($1::uuid,'simulated_fill','intraday_stocks',$2,'TESTP6','BUY',10,100,95,110,500,"
                  "'closed',500)", CORR, TOK)
    await execute("INSERT INTO positions (correlation_id, mode, sleeve, instrument_token, tradingsymbol, side, "
                  "quantity, entry_price, stop_price, target_price, r_rupees, status, unrealized_pnl) "
                  "VALUES ($1::uuid,'simulated_fill','intraday_stocks',$2,'TESTP6B','BUY',10,100,95,110,500,"
                  "'open',200)", CORR, TOK)


async def checks() -> dict:
    r = {}

    acct = await services.account()
    r["account"] = ("live_capital" in acct and "mode" in acct and acct["live_capital"] > 0,
                    f"capital={acct.get('live_capital')} mode={acct.get('mode')}")

    pnl = await services.pnl_today()
    r["pnl_today"] = (pnl["realized"] >= 500 and pnl["unrealized"] >= 200 and "killswitch_limit" in pnl,
                      f"realized={pnl['realized']} unrealized={pnl['unrealized']} ks_limit={pnl['killswitch_limit']}")

    pos = await services.positions()
    seeded = [p for p in pos if p.get("instrument") in ("TESTP6", "TESTP6B")]
    r["positions"] = (len(seeded) >= 1, f"{len(pos)} open; seeded-open shows={bool(seeded)}")

    sig = await services.signals(limit=20)
    mine = next((s for s in sig if s["correlation_id"] == CORR), None)
    r["signals_gate_trail"] = (mine is not None and len(mine["gates"]) == 3 and mine["decision"] == "PASS",
                               f"found={mine is not None} gates={mine and len(mine['gates'])}")

    rec = await services.reconstruct(CORR)
    r["reconstruction"] = (rec["signal"] and len(rec["gates"]) == 3 and len(rec["events"]) >= 3 and len(rec["positions"]) >= 2,
                           f"signal={bool(rec['signal'])} gates={len(rec['gates'])} events={len(rec['events'])} pos={len(rec['positions'])}")

    rk = await services.risk()
    sl = await services.sleeves()
    cf = await services.config_view()
    hl = await services.health()
    pc = await services.prelive_checklist()
    r["risk_sleeves_config_health"] = (
        "open_R" in rk and len(sl) == 4 and "risk" in cf and "session_state" in hl and "compliance_tagging" in pc,
        f"sleeves={len(sl)} session={hl.get('session_state')} prelive_keys={list(pc)}")

    # ---- control route functions (state + command enqueue + guard) ----
    await control_pause(PauseBody(paused=True))
    r["control_pause"] = (await get_state("engine_paused", False) is True, "engine_paused set")

    await control_flatten(ConfirmBody(confirm=True))
    rc = await get_redis()
    qlen = await rc.llen(COMMANDS_KEY)
    r["control_flatten_enqueues"] = (qlen >= 1, f"command queue len={qlen}")

    live_guarded = False
    try:
        await control_mode(ModeBody(mode="live"))  # no token -> must reject
    except HTTPException:
        live_guarded = True
    res_live = await control_mode(ModeBody(mode="live", confirm_token="LIVE"))
    mode_after = await get_state("execution_mode", "simulated_fill")
    r["control_mode_golive_guard"] = (live_guarded and res_live["mode"] == "live" and mode_after == "live",
                                      f"guarded_without_token={live_guarded} mode_after={mode_after}")

    await control_sleeve("fno", SleeveBody(enabled=False))
    r["control_sleeve"] = (await get_state("sleeve_fno_enabled", True) is False, "fno disabled")

    await control_ks_reset(ConfirmBody(confirm=True))
    r["control_ks_reset"] = (await get_state("kill_switch_active", True) is False
                             and await get_state("engine_halted", True) is False, "kill-switch/halt cleared")

    await close_position(str(TOK), ConfirmBody(confirm=True))
    r["control_close_enqueues"] = (await rc.llen(COMMANDS_KEY) >= 2, "close command enqueued")

    # ---- WebSocket event bus ----
    ps = rc.pubsub()
    await ps.subscribe(EVENTS_CHANNEL)
    await asyncio.sleep(0.1)
    await publish_event("phase6_test", {"hello": 1})
    got = None
    for _ in range(20):
        m = await ps.get_message(ignore_subscribe_messages=True, timeout=0.5)
        if m and m.get("type") == "message":
            d = json.loads(m["data"])
            if d.get("type") == "phase6_test":
                got = d
                break
    await ps.unsubscribe(EVENTS_CHANNEL)
    await ps.aclose()
    r["ws_event_bus"] = (got is not None and got["payload"]["hello"] == 1, f"received={got is not None}")
    return r


async def cleanup():
    # CRITICAL: restore safe shared state + clear the command queue so the live engine
    # is unaffected, then drop seeded rows.
    await set_state("engine_paused", False, "verify")
    await set_state("engine_halted", False, "verify")
    await set_state("kill_switch_active", False, "verify")
    await set_state("execution_mode", "simulated_fill", "verify")
    await set_state("sleeve_fno_enabled", True, "verify")
    try:
        rc = await get_redis()
        await rc.delete(COMMANDS_KEY)
    except Exception:
        pass
    for t in ("gate_results", "audit_log", "positions", "signals"):
        try:
            await execute(f"DELETE FROM {t} WHERE correlation_id=$1::uuid", CORR)
        except Exception:
            pass


async def main():
    configure_logging()
    await init_pool()
    results = {}
    try:
        await seed()
        results = await checks()
    except Exception as exc:
        results["ERROR"] = (False, f"{type(exc).__name__}: {exc}")
    finally:
        await cleanup()
        await close_pool()

    print("\n=== PHASE 6 ACCEPTANCE ===")
    overall = True
    for name, (passed, detail) in results.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
        overall = overall and passed
    print("RESULT:", "PASS ✅" if overall and results else "FAIL ❌")
    sys.exit(0 if overall and results else 1)


if __name__ == "__main__":
    asyncio.run(main())
