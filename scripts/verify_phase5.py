"""Phase 5 acceptance (Decision Orchestrator + Confidence + LLM).

End-to-end: a qualifying setup flows pipeline -> confidence -> risk sizing ->
LLM veto -> simulated order, with the complete reasoning chain in the audit log.
Also proves: the LLM veto blocks a trade, an LLM downsize shrinks it, a pipeline
reject short-circuits, and the LLM layer FAILS NEUTRAL on error. Hermetic: static
capital, a patched sim price, and a stub LLM (no network); test rows cleaned up.
"""
from __future__ import annotations

import sys

from common.db import close_pool, execute, fetch, fetchval, init_pool
from common.logging import configure_logging
from config.loader import get_config
from config.settings import get_settings
from engine.confidence import ConfidenceModel
from engine.orchestrator import DecisionOrchestrator
from execution.executor import build_executor
from llm.context import LLMContextLayer, StubLLMContextLayer
from risk.capital import CapitalReader
from risk.engine import RiskEngine
from strategies.base import GateResult
from strategies.fno import FnoPipeline
from strategies.intraday import IntradayContext, IntradayPipeline

cfg = get_config()
settings = get_settings()
CORRS: list[str] = []


def _intra(regime: str = "trending_up") -> IntradayContext:
    return IntradayContext(last_price=105, or_high=104, or_low=100, vwap=103, rvol=2.2,
                           daily_adv=3_000_000, spread_pct=0.05, gap_pct=0.8, regime=regime,
                           sector_strong=True, now_window_ok=True)


def _orch(verdict: dict | None):
    executor = build_executor(cfg, adapter=None, governor=None)

    async def _fixed_quote(instrument, side):
        return 105.0
    executor.sim.quote_price = _fixed_quote  # hermetic sim fill (no network)
    risk = RiskEngine(cfg, capital_reader=CapitalReader(static_capital=300_000), mode="simulated_fill")
    pipelines = {"intraday_stocks": IntradayPipeline(cfg), "fno": FnoPipeline(cfg)}
    llm = StubLLMContextLayer(verdict)
    return DecisionOrchestrator(cfg, pipelines, ConfidenceModel(cfg), risk, executor, llm), executor


def _inst(token: int) -> dict:
    return {"instrument_token": token, "tradingsymbol": f"VERIFY5_{token}",
            "exchange": "NSE", "lot_size": 1, "instrument_type": "EQ"}


async def _events(corr: str) -> list[str]:
    rows = await fetch("SELECT event_type FROM audit_log WHERE correlation_id=$1::uuid ORDER BY ts", corr)
    return [r["event_type"] for r in rows]


async def c_end_to_end_with_audit_chain():
    orch, ex = _orch({"sentiment": "neutral", "event_risk": "low", "veto": False, "downsize": 1.0, "reason": "clear"})
    res = await orch.evaluate("intraday_stocks", _inst(990000001), _intra())
    CORRS.append(res["correlation_id"])
    ev = await _events(res["correlation_id"])
    sigs = await fetchval("SELECT count(*) FROM signals WHERE correlation_id=$1::uuid", res["correlation_id"])
    gates = await fetchval("SELECT count(*) FROM gate_results WHERE correlation_id=$1::uuid", res["correlation_id"])
    chain_ok = all(e in ev for e in ("pipeline_evaluated", "risk_sized", "llm_verdict", "executed")) and sigs == 1 and gates > 0
    ok = res["status"] == "executed" and res.get("position_id") and res.get("qty", 0) > 0 and chain_ok
    if res.get("position_id"):
        await ex.close(res["position_id"], "verify_cleanup", price=105.0)
    return ok, f"status={res['status']} qty={res.get('qty')} conf={res.get('confidence')} gates={gates} chain={ev}"


async def c_llm_veto_blocks():
    orch, ex = _orch({"sentiment": "negative", "event_risk": "high", "veto": True, "downsize": 1.0, "reason": "fraud probe"})
    res = await orch.evaluate("intraday_stocks", _inst(990000002), _intra())
    CORRS.append(res["correlation_id"])
    ev = await _events(res["correlation_id"])
    ok = (res["status"] == "skip" and "LLM veto" in (res["reason"] or "") and not res.get("position_id")
          and "llm_verdict" in ev and "executed" not in ev)
    return ok, f"status={res['status']} reason={res['reason']} chain={ev}"


async def c_llm_downsize_shrinks():
    orch1, ex1 = _orch({"veto": False, "downsize": 1.0, "reason": "ok", "sentiment": "neutral", "event_risk": "low"})
    full = await orch1.evaluate("intraday_stocks", _inst(990000003), _intra())
    CORRS.append(full["correlation_id"])
    if full.get("position_id"):
        await ex1.close(full["position_id"], "verify_cleanup", price=105.0)
    orch2, ex2 = _orch({"veto": False, "downsize": 0.5, "reason": "trim on event risk", "sentiment": "neutral", "event_risk": "medium"})
    half = await orch2.evaluate("intraday_stocks", _inst(990000004), _intra())
    CORRS.append(half["correlation_id"])
    if half.get("position_id"):
        await ex2.close(half["position_id"], "verify_cleanup", price=105.0)
    ok = full["status"] == "executed" and half["status"] == "executed" and 0 < half["qty"] < full["qty"]
    return ok, f"full_qty={full.get('qty')} downsized_qty={half.get('qty')}"


async def c_pipeline_reject_short_circuits():
    orch, _ = _orch(None)
    res = await orch.evaluate("intraday_stocks", _inst(990000005), _intra(regime="choppy"))
    CORRS.append(res["correlation_id"])
    ev = await _events(res["correlation_id"])
    ok = (res["status"] == "skip" and "choppy" in (res["reason"] or "")
          and "risk_sized" not in ev and "llm_verdict" not in ev and "executed" not in ev)
    return ok, f"status={res['status']} reason={res['reason']} chain={ev}"


async def c_llm_fail_neutral():
    llm = LLMContextLayer(cfg, settings)
    llm.provider = None  # force the no-provider path -> fail neutral
    v = await llm.assess({"tradingsymbol": "X", "exchange": "NSE"},
                         {"side": "BUY", "setup": "orb", "sleeve": "intraday_stocks"})
    ok = v["veto"] is False and v["downsize"] == 1.0 and "fail neutral" in v["reason"].lower()
    return ok, f"verdict={v}"


async def c_confidence_weighting():
    cm = ConfidenceModel(cfg)
    gates = [GateResult("regime", True, 1.0), GateResult("confirmation", True, 0.8),
             GateResult("liquidity", True, 0.6)]
    s = cm.score(gates)
    # weighted: regime/confirmation are up-weighted -> pulled above the plain mean (0.8)
    ok = 0.0 < s <= 1.0 and cm.passes(0.9) and not cm.passes(0.2)
    return ok, f"score={s} min_confidence={cm.min_confidence}"


async def _cleanup():
    for corr in CORRS:
        try:
            await execute("DELETE FROM positions   WHERE correlation_id=$1::uuid", corr)
            await execute("DELETE FROM audit_log    WHERE correlation_id=$1::uuid", corr)
            await execute("DELETE FROM gate_results WHERE correlation_id=$1::uuid", corr)
            await execute("DELETE FROM signals      WHERE correlation_id=$1::uuid", corr)
        except Exception:
            pass


async def main():
    configure_logging()
    await init_pool()
    checks = {
        "end_to_end_sim_order_+_audit_chain": c_end_to_end_with_audit_chain,
        "llm_veto_blocks_trade": c_llm_veto_blocks,
        "llm_downsize_shrinks_qty": c_llm_downsize_shrinks,
        "pipeline_reject_short_circuits": c_pipeline_reject_short_circuits,
        "llm_fail_neutral_on_no_key": c_llm_fail_neutral,
        "confidence_weighted_combination": c_confidence_weighting,
    }
    results = {}
    for name, fn in checks.items():
        try:
            results[name] = await fn()
        except Exception as exc:
            results[name] = (False, f"error: {exc}")
    await _cleanup()
    await close_pool()

    print("\n=== PHASE 5 ACCEPTANCE ===")
    overall = True
    for name, (passed, detail) in results.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
        overall = overall and passed
    print("==========================")
    print("RESULT:", "PASS ✅" if overall else "FAIL ❌")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
