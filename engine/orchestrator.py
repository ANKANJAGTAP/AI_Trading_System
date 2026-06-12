"""Decision Orchestrator (spec §6) — the slow-loop decision chain:

    pipeline gates -> all PASS? --no--> skip
          | yes
    confidence score -> below min? --yes--> skip
          | no
    Risk Engine sizing (R, margin, caps) -> rejected? --yes--> skip
          | no
    LLM context veto? --yes--> skip ; downsize? --> reduce qty
          | no
    Execution Layer (sim/live)

Every step is written to the audit log + signals/gate_results under one
correlation_id so any decision is fully reconstructable. The LLM can only veto or
downsize — never originate. F&O produces a risk-sized defined-risk structure
(multi-leg execution is a Phase 3 extension); equity/MCX sleeves execute end-to-end.
"""
from __future__ import annotations

import math

from common.audit import audit, new_correlation_id, persist_gates, persist_signal
from common.db import fetch
from common.events import publish_event
from common.logging import get_logger
from execution.models import Decision
from strategies.base import PASS

log = get_logger("orchestrator")

_PRODUCT = {"intraday_stocks": "MIS", "swing_stocks": "CNC", "fno": "NRML", "mcx_commodities": "NRML"}


class DecisionOrchestrator:
    def __init__(self, config, pipelines: dict, confidence_model, risk_engine, executor, llm,
                 alerter=None, meta_labeler=None) -> None:
        self.config = config
        self.pipelines = pipelines
        self.confidence = confidence_model
        self.risk = risk_engine
        self.executor = executor
        self.llm = llm
        self.alerter = alerter
        self.meta_labeler = meta_labeler   # Phase 4: opt-in confidence filter (or None)

    async def evaluate(self, sleeve: str, instrument: dict, ctx) -> dict:
        """Run the decision chain, then push a real-time signal_evaluated (Gate Trail)
        + order_event to the dashboard. Publishing is best-effort."""
        res = await self._evaluate(sleeve, instrument, ctx)
        try:
            gates = []
            if res.get("signal_id"):
                rows = await fetch("SELECT gate_name, passed, score FROM gate_results "
                                   "WHERE signal_id=$1 ORDER BY id", res["signal_id"])
                gates = [{"name": r["gate_name"], "pass": r["passed"], "score": float(r["score"] or 0)} for r in rows]
            await publish_event("signal_evaluated", {
                "correlation_id": res.get("correlation_id"), "sleeve": sleeve,
                "instrument": instrument.get("tradingsymbol"), "gates": gates,
                "status": res.get("status"), "confidence": res.get("confidence"),
                "reason": res.get("reason"), "structure": res.get("structure"),
                "outcome": res.get("outcome"), "llm": res.get("llm")})
            if res.get("status") in ("executed", "sized_structure"):
                await publish_event("order_event", {
                    "correlation_id": res.get("correlation_id"), "status": "filled",
                    "instrument": instrument.get("tradingsymbol"), "sleeve": sleeve,
                    "qty": res.get("qty"), "structure": res.get("structure"),
                    "position_id": res.get("position_id")})
        except Exception as exc:
            log.warning("publish_signal_failed", error=str(exc))
        return res

    async def _evaluate(self, sleeve: str, instrument: dict, ctx) -> dict:
        corr = new_correlation_id()
        pipeline = self.pipelines.get(sleeve)
        if pipeline is None:
            return {"status": "skip", "reason": f"no pipeline for {sleeve}", "correlation_id": corr}

        result = await pipeline.evaluate(instrument, ctx)
        confidence = self.confidence.score(result.gates)
        # Phase 4: rich feature vector (continuous context values + gate scores) captured
        # per signal so the meta-labeler/discrimination has features that actually vary.
        from research.features import signal_features
        features = signal_features(sleeve, ctx, confidence, result.gates, signal=result.signal)
        # meta-label filter — a learned model can only SHRINK confidence (potentially
        # below min -> skip). Never originates or inflates.
        if self.meta_labeler is not None and result.decision == PASS:
            try:
                confidence = round(confidence * self.meta_labeler.assess(features), 4)
                features["confidence"] = confidence
            except Exception as exc:
                log.warning("meta_label_failed", error=str(exc))
        signal_id = await persist_signal(sleeve, instrument, result.decision, confidence,
                                         result.reason, corr, result.signal, features=features)
        await persist_gates(signal_id, corr, result.gates)
        await audit("pipeline_evaluated", "orchestrator", f"{result.decision}: {result.reason or 'signal'}",
                    corr, {"sleeve": sleeve, "symbol": instrument.get("tradingsymbol"),
                           "confidence": confidence, "gates": result.trail})

        if result.decision != PASS:
            return {"status": "skip", "reason": result.reason, "correlation_id": corr, "signal_id": signal_id}

        if not self.confidence.passes(confidence):
            await audit("skip_low_confidence", "orchestrator", f"confidence {confidence} < min", corr,
                        {"confidence": confidence})
            return {"status": "skip", "reason": f"confidence {confidence} below minimum",
                    "correlation_id": corr, "signal_id": signal_id, "confidence": confidence}

        signal = result.signal

        # Risk Engine sizing
        if sleeve == "fno":
            ml = signal.detail.get("max_loss_per_lot", 0)
            lot = signal.detail.get("lot_size", 1)
            sized = await self.risk.size_structure(
                ml, lot, sleeve, confidence,
                underlying=instrument.get("tradingsymbol"), expiry=getattr(ctx, "expiry", None),
                structure=signal.detail.get("structure"))
        else:
            sized = await self.risk.size(signal.entry, signal.stop, instrument, sleeve, confidence, side=signal.side)
        await audit("risk_sized", "orchestrator",
                    "REJECT" if sized.rejected else f"qty={sized.quantity}", corr,
                    {"rejected": sized.rejected, "reason": sized.reason, "quantity": sized.quantity,
                     "r_rupees": sized.r_intended, "clamps": sized.clamps})
        if sized.rejected:
            return {"status": "skip", "reason": f"risk: {sized.reason}",
                    "correlation_id": corr, "signal_id": signal_id, "confidence": confidence}

        # LLM veto / downsize (after sizing — can only block or shrink)
        verdict = await self.llm.assess(instrument, {"side": signal.side, "setup": signal.setup, "sleeve": sleeve})
        await audit("llm_verdict", "orchestrator", verdict.get("reason", ""), corr, verdict)
        if verdict.get("veto"):
            return {"status": "skip", "reason": f"LLM veto: {verdict.get('reason')}",
                    "correlation_id": corr, "signal_id": signal_id, "confidence": confidence, "llm": verdict}

        qty = sized.quantity
        lot = sized.lot_size or 1
        downsize = float(verdict.get("downsize", 1.0))

        # F&O: open the sized defined-risk structure (multi-leg sim execution)
        if sleeve == "fno":
            # Downsize REDUCES size; it never discards a risk-approved structure. A
            # full block is the LLM's veto (handled above), not a fractional downsize.
            # Keep at least the 1-lot minimum the risk engine already approved.
            lots = max(1, round(sized.lots * downsize)) if downsize < 1.0 else sized.lots
            structure = signal.detail.get("structure")
            res = await self.executor.execute_structure(
                name=instrument.get("tradingsymbol"), expiry=ctx.expiry, structure=structure,
                lots=lots, lot_size=ctx.lot_size, strike_step=ctx.strike_step,
                correlation_id=corr, signal_id=signal_id)
            await audit("structure_executed", "orchestrator", (structure or {}).get("type", ""), corr,
                        {"outcome": res.get("outcome"), "lots": lots, "net_premium": res.get("net_premium"),
                         "max_loss": res.get("max_loss"), "reason": res.get("reason")})
            status = "executed" if res.get("outcome") == "FILLED" else "rejected"
            return {"status": status, "outcome": res.get("outcome"), "correlation_id": corr,
                    "signal_id": signal_id, "confidence": confidence, "structure": (structure or {}).get("type"),
                    "lots": lots, "net_premium": res.get("net_premium"), "max_loss": res.get("max_loss"),
                    "position_ids": res.get("position_ids"), "llm": verdict}

        # equity / MCX: single-instrument order
        if downsize < 1.0:
            scaled = qty * downsize
            qty = int(math.floor(scaled / lot) * lot) if lot > 1 else int(math.floor(scaled))
            if qty < lot:
                await audit("skip_downsized_below_min", "orchestrator", "LLM downsize below 1 unit", corr,
                            {"downsize": downsize})
                return {"status": "skip", "reason": "LLM downsize below 1 unit",
                        "correlation_id": corr, "signal_id": signal_id, "llm": verdict}

        # Cost-aware edge gate: if round-trip costs eat more than the configured
        # fraction of the reward at target, the trade has no edge worth paying for —
        # heavily-clamped (tiny) positions otherwise bleed fees against micro-profits.
        max_cost_frac = float(getattr(self.config.risk, "cost_edge_max_fraction", 0.15) or 0)
        if max_cost_frac and signal.target:
            seg = self.executor.cost.segment_key(sleeve, instrument.get("instrument_type"))
            round_trip = self.executor.cost.round_trip_cost(seg, qty, signal.entry, signal.target)
            reward_rupees = abs(signal.target - signal.entry) * qty
            if reward_rupees <= 0 or round_trip > reward_rupees * max_cost_frac:
                await audit("skip_cost_edge", "orchestrator",
                            f"costs Rs {round_trip:.0f} > {max_cost_frac:.0%} of reward Rs {reward_rupees:.0f}",
                            corr, {"round_trip": round_trip, "reward": reward_rupees})
                return {"status": "skip", "reason": "round-trip costs eat the edge",
                        "correlation_id": corr, "signal_id": signal_id, "confidence": confidence}

        # r_rupees = the risk ACTUALLY carried (qty x stop distance after all clamps),
        # not the intended R budget. With tight stops the per-instrument cap can clamp
        # actual risk to a fraction of R — recording r_intended overstated open-R ~40x
        # and made every R-multiple (expectancy guard, analytics) meaningless.
        actual_r = float(qty) * abs(signal.entry - signal.stop)
        decision = Decision(
            correlation_id=corr, sleeve=sleeve, instrument=instrument, side=signal.side,
            quantity=qty, order_type="MARKET", entry_price=signal.entry, stop_price=signal.stop,
            target_price=signal.target, product=_PRODUCT.get(sleeve, "MIS"),
            r_rupees=round(actual_r, 2), confidence=confidence, signal_id=signal_id,
        )
        exec_result = await self.executor.execute(decision)
        await audit("executed", "orchestrator", str(exec_result.outcome), corr,
                    {"outcome": exec_result.outcome, "position_id": exec_result.position_id,
                     "qty": exec_result.filled_quantity, "avg_price": exec_result.avg_price,
                     "fees": exec_result.fees_total, "reason": exec_result.reason})
        status = "executed" if exec_result.outcome in ("FILLED", "PARTIAL") else "rejected"
        return {"status": status, "outcome": exec_result.outcome, "correlation_id": corr,
                "signal_id": signal_id, "position_id": exec_result.position_id,
                "confidence": confidence, "qty": exec_result.filled_quantity, "llm": verdict}
