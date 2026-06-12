"""F&O multi-leg execution acceptance: live FnoContext -> pipeline -> risk-sized
structure -> multi-leg SIM open -> combined-P&L mark -> close, with the full audit
chain. Static ₹10L paper capital. Self-cleaning by correlation_id. Run market hours.
"""
from __future__ import annotations

import asyncio
import sys

from broker.kite_adapter import KiteAdapter
from common.alerts import Alerter
from common.db import close_pool, execute, fetch, init_pool
from common.logging import configure_logging
from config.loader import get_config
from config.settings import get_settings
from data.historical import incremental_backfill
from data.instruments import get_token
from data.rate_governor import RateGovernor
from engine.confidence import ConfidenceModel
from engine.context_builder import build_fno_context
from engine.orchestrator import DecisionOrchestrator
from execution.executor import build_executor
from execution.structures import close_structure, mark_structures
from llm.context import StubLLMContextLayer
from risk.capital import CapitalReader
from risk.engine import RiskEngine
from strategies.fno import FnoPipeline


async def main():
    configure_logging()
    await init_pool()
    cfg, settings = get_config(), get_settings()
    adapter = KiteAdapter(settings, Alerter(settings))
    await asyncio.to_thread(adapter.ensure_token)
    gov = RateGovernor(cfg.data.rate_limits)

    vtok = await get_token("NSE:INDIA VIX")
    if vtok:
        try:
            await incremental_backfill(adapter, gov, vtok, "day", 300, 200)
        except Exception:
            pass

    executor = build_executor(cfg, adapter, gov)
    risk = RiskEngine(cfg, capital_reader=CapitalReader(adapter, gov, static_capital=1_000_000),
                      adapter=adapter, governor=gov, mode="simulated_fill")
    orch = DecisionOrchestrator(
        cfg, {"fno": FnoPipeline(cfg)}, ConfidenceModel(cfg), risk, executor,
        StubLLMContextLayer({"veto": False, "downsize": 1.0, "reason": "ok",
                             "sentiment": "neutral", "event_risk": "low"}))

    results, corr = {}, None
    utok = await get_token("NSE:NIFTY 50")
    ctx = await build_fno_context(adapter, gov, "NIFTY", "NSE:NIFTY 50", utok, cfg.strategy.fno)
    if ctx is None:
        results["fno_context"] = (False, "context=None (no expiry in window / data)")
    else:
        inst = {"tradingsymbol": "NIFTY", "exchange": "NFO", "instrument_type": "CE", "lot_size": ctx.lot_size}
        res = await orch.evaluate("fno", inst, ctx)
        corr = res.get("correlation_id")
        legs = res.get("position_ids") or []
        results["fno_multileg_open"] = (
            res["status"] == "executed" and res.get("outcome") == "FILLED" and len(legs) >= 2,
            f"status={res['status']} struct={res.get('structure')} lots={res.get('lots')} "
            f"legs={len(legs)} net_premium={res.get('net_premium')} max_loss={res.get('max_loss')}")

        ev = [r["event_type"] for r in await fetch(
            "SELECT event_type FROM audit_log WHERE correlation_id=$1::uuid ORDER BY ts", corr)]
        results["fno_audit_chain"] = (
            all(e in ev for e in ("pipeline_evaluated", "risk_sized", "llm_verdict", "structure_executed")),
            f"chain={ev}")

        marks = await mark_structures(executor, adapter, gov)
        results["fno_combined_mtm"] = (len(marks) >= 1, f"marks={marks}")

        for g in list(executor.structures.all()):
            await close_structure(executor, g, "verify_cleanup")
        results["fno_structure_closed"] = (len(executor.structures.all()) == 0, "all legs closed + unregistered")

    if corr:
        for t in ("positions", "audit_log", "gate_results", "signals"):
            try:
                await execute(f"DELETE FROM {t} WHERE correlation_id=$1::uuid", corr)
            except Exception:
                pass
    await close_pool()

    print("\n=== F&O EXECUTION VERIFY ===")
    overall = True
    for name, (passed, detail) in results.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
        overall = overall and passed
    print("RESULT:", "PASS ✅" if overall and results else "FAIL ❌")
    sys.exit(0 if overall and results else 1)


if __name__ == "__main__":
    asyncio.run(main())
