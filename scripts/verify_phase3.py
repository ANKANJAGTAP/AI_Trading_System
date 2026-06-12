"""Phase 3 acceptance (Execution & Order Management). Runs in simulated_fill on real
live prices (safe alongside the engine — writes positions, not candles).

  1. sim fill -> cost-adjusted, OCO/guard bracket created
  2. guard exit (target) -> close with cost-adjusted realized PnL
  3. partial fill -> position + bracket sized to filled qty
  4. crash recovery -> fresh Executor adopts open position + re-arms guard
  5. recovery flags a position with no protective stop
  6. fail-safe -> squares off all + halts -> new entries blocked
  7. reconciliation -> flags an injected book/broker mismatch
  8. freeze-quantity slicing
"""
from __future__ import annotations

import asyncio
import sys
import uuid

from broker.kite_adapter import KiteAdapter
from common.db import close_pool, execute, fetchrow, init_pool
from common.logging import configure_logging, get_logger
from common.redis_client import close_redis, get_redis
from common.state import get_state, set_state
from config.loader import get_config
from config.settings import get_settings
from data.instruments import resolve
from data.rate_governor import RateGovernor
from execution.executor import Executor, build_executor
from execution.failsafe import safe_exit_all
from execution.models import Decision, OrderOutcome

log = get_logger("verify_phase3")
_created: list[int] = []


async def _decision(adapter, governor, qty=10) -> Decision:
    inst = dict(await resolve("NSE:RELIANCE"))
    inst["exchange"] = "NSE"
    q = await governor.call("quote", adapter.quote, ["NSE:RELIANCE"])
    entry = float(q["NSE:RELIANCE"]["last_price"])
    return Decision(
        correlation_id=str(uuid.uuid4()), sleeve="intraday_stocks", instrument=inst,
        side="BUY", quantity=qty, order_type="MARKET", entry_price=entry,
        stop_price=round(entry * 0.99, 2), target_price=round(entry * 1.02, 2),
        product="MIS", r_rupees=1000.0,
    )


async def c_sim_fill(ex, a, g):
    res = await ex.execute(await _decision(a, g))
    if res.position_id:
        _created.append(res.position_id)
    armed = res.position_id in ex.guards.armed_ids()
    ok = res.outcome == OrderOutcome.FILLED and res.filled_quantity == 10 and res.fees_total > 0 and res.bracket and armed
    return ok, f"{res.outcome} qty={res.filled_quantity} entry={res.avg_price} fees=Rs{res.fees_total} bracket={res.bracket and res.bracket['type']} guard={armed}"


async def c_guard_exit(ex, a, g):
    d = await _decision(a, g)
    res = await ex.execute(d)
    _created.append(res.position_id)
    realized = await ex.on_price(res.position_id, d.target_price)  # hit target
    gross = (d.target_price - res.avg_price) * 10
    ok = realized is not None and realized < gross  # net below gross due to costs
    return ok, f"entry={res.avg_price} target={d.target_price} gross~{gross:.1f} realized={realized}"


async def c_partial(ex, a, g):
    res = await ex.execute(await _decision(a, g, qty=10), force_fill_qty=6)
    _created.append(res.position_id)
    pos = await fetchrow("SELECT quantity FROM positions WHERE id=$1", res.position_id)
    ok = res.outcome == OrderOutcome.PARTIAL and res.filled_quantity == 6 and int(pos["quantity"]) == 6 and res.bracket["quantity"] == 6
    return ok, f"{res.outcome} filled={res.filled_quantity} pos_qty={pos['quantity']} bracket_qty={res.bracket['quantity']}"


async def c_recovery_rearm(ex, a, g):
    res = await ex.execute(await _decision(a, g))
    _created.append(res.position_id)
    fresh = build_executor(get_config(), a, g)  # simulate restart: empty GuardManager
    pre = res.position_id in fresh.guards.armed_ids()
    out = await fresh.adopt_open_positions()
    rearmed = res.position_id in fresh.guards.armed_ids()
    ok = (not pre) and rearmed and any(x["id"] == res.position_id for x in out["adopted"])
    return ok, f"pre_armed={pre} adopted={len(out['adopted'])} rearmed={rearmed}"


async def c_recovery_flag(ex, a, g):
    row = await fetchrow(
        "INSERT INTO positions (correlation_id, mode, sleeve, instrument_token, tradingsymbol, side, "
        "quantity, average_price, entry_price, status) VALUES (gen_random_uuid(),'simulated_fill',"
        "'intraday_stocks',738561,'RELIANCE','BUY',5,1280,1280,'open') RETURNING id")
    _created.append(row["id"])
    out = await build_executor(get_config(), a, g).adopt_open_positions()
    flagged = any(f["id"] == row["id"] for f in out["flagged"])
    return flagged, f"missing_stop_flagged={flagged} (total flagged={len(out['flagged'])})"


async def c_failsafe(ex, a, g):
    res = await ex.execute(await _decision(a, g))
    _created.append(res.position_id)
    fs = await safe_exit_all(ex, "verify-injected fault")
    halted = await get_state("engine_halted", False)
    res2 = await ex.execute(await _decision(a, g))
    if res2.position_id:
        _created.append(res2.position_id)
    blocked = res2.outcome == OrderOutcome.REJECTED and "halt" in (res2.reason or "")
    await set_state("engine_halted", False, "test")
    await set_state("engine_paused", False, "test")
    pos = await fetchrow("SELECT status FROM positions WHERE id=$1", res.position_id)
    ok = pos["status"] == "closed" and halted and blocked
    return ok, f"squared_off={pos['status']} halted={halted} new_entry_blocked={blocked} closed={len(fs['closed'])}"


async def c_reconcile(ex):
    row = await fetchrow(
        "INSERT INTO positions (correlation_id, mode, sleeve, instrument_token, tradingsymbol, side, "
        "quantity, average_price, entry_price, stop_price, status) VALUES (gen_random_uuid(),'live',"
        "'intraday_stocks',738561,'RELIANCE','BUY',5,1280,1280,1260,'open') RETURNING id")
    _created.append(row["id"])
    mismatch = await ex.book.reconcile(broker_net_positions=[], mode="live")          # broker has none
    clean = await ex.book.reconcile(broker_net_positions=[{"instrument_token": 738561, "quantity": 5}], mode="live")
    ok = any(m["instrument_token"] == 738561 for m in mismatch) and not clean
    return ok, f"mismatch_flagged={len(mismatch)} clean_when_matched={not clean}"


def c_freeze_slice():
    s1, s2 = Executor._slice(1000, 300), Executor._slice(50, 0)
    return (s1 == [300, 300, 300, 100] and s2 == [50]), f"slice(1000,300)={s1} slice(50,0)={s2}"


async def _cleanup():
    r = await get_redis()
    for pid in set(_created):
        try:
            await execute("DELETE FROM positions WHERE id=$1", pid)
            await r.srem("positions:open", str(pid))
            await r.delete(f"pos:{pid}")
        except Exception:
            pass
    await set_state("engine_halted", False, "test")
    await set_state("engine_paused", False, "test")


async def main():
    configure_logging()
    await init_pool()
    adapter = KiteAdapter(get_settings())
    adapter.ensure_token()
    governor = RateGovernor(get_config().data.rate_limits)
    await set_state("execution_mode", "simulated_fill", "test")
    await set_state("engine_halted", False, "test")
    ex = build_executor(get_config(), adapter, governor)

    results: dict = {}
    try:
        results["sim_fill_cost_bracket"] = await c_sim_fill(ex, adapter, governor)
        results["guard_exit_costadj_pnl"] = await c_guard_exit(ex, adapter, governor)
        results["partial_fill_bracket_resize"] = await c_partial(ex, adapter, governor)
        results["crash_recovery_rearm"] = await c_recovery_rearm(ex, adapter, governor)
        results["recovery_flags_no_stop"] = await c_recovery_flag(ex, adapter, governor)
        results["failsafe_exit_and_halt"] = await c_failsafe(ex, adapter, governor)
        results["reconciliation_mismatch"] = await c_reconcile(ex)
        results["freeze_qty_slicing"] = c_freeze_slice()
    finally:
        await _cleanup()
        await close_pool()
        await close_redis()

    print("\n=== PHASE 3 ACCEPTANCE ===")
    overall = True
    for name, (passed, detail) in results.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
        overall = overall and passed
    print("==========================")
    print("RESULT:", "PASS ✅" if overall else "FAIL ❌")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    asyncio.run(main())
