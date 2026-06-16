"""Execution layer (spec §8) — the single switch between simulated_fill (default)
and live, behind which the order lifecycle, brackets, position book, guards,
crash-recovery and fail-safe are wired.

simulated_fill: real signals + real live prices + realistic fill + full cost model,
NO real order sent. live: real Kite orders, freeze-quantity slicing, reason-aware
rejection handling (no blind retry), bracket sized to the actually-filled quantity.
"""
from __future__ import annotations

import asyncio
import time

from common.db import fetchrow
from common.logging import get_logger
from common.errors import UnsafeLiveState
from common.market_time import now_ist
from common.state import get_state
from data.instruments import get_instrument
from execution.brackets import create_bracket
from execution.costs import CostModel
from execution.guards import GuardManager
from execution.models import Decision, ExecutionResult, ExitReason, Fill, OrderOutcome
from execution.policy import exit_product_supported, live_structures_block_reason
from execution.position_book import PositionBook
from execution.recovery import adopt_open_positions
from execution.simulator import FillSimulator
from execution.structures import StructureManager, open_structure

log = get_logger("executor")


class Executor:
    def __init__(self, config, adapter, governor, book, cost_model, simulator, guards, alerter=None) -> None:
        self.config = config
        self.adapter = adapter
        self.governor = governor
        self.book = book
        self.cost = cost_model
        self.sim = simulator
        self.guards = guards
        self.structures = StructureManager()   # F&O multi-leg structures
        self.alerter = alerter
        self.mode = config.execution.mode
        # Fast-loop DB-write throttle: unrealized P&L is flushed to Postgres at most
        # once per interval per position; every tick still updates Redis cheaply.
        self._last_persist: dict[int, float] = {}
        self._persist_interval = 2.0

    # --- helpers ---------------------------------------------------------
    async def current_mode(self) -> str:
        # P0#1: single source of truth (RuntimeModeState); legacy key as fallback.
        try:
            from common.runtime_mode import load_runtime_mode
            self.mode = (await load_runtime_mode()).mode
        except Exception:
            self.mode = await get_state("execution_mode", self.config.execution.mode)
        return self.mode

    def square_off_time(self, sleeve: str) -> str | None:
        if sleeve == "intraday_stocks":
            return (self.config.strategy.intraday_stocks.get("time_gates") or {}).get("hard_exit")
        if sleeve == "mcx_commodities":
            # intraday commodity positions must die before the MCX close — there was
            # no square-off here at all (overnight futures with no hard exit).
            return (self.config.strategy.mcx_commodities.get("session") or {}).get("hard_exit")
        return None

    def _freeze_limit(self, instrument: dict) -> int:
        fq = self.config.execution.freeze_quantity or {}
        # Exchange freeze qty is per-instrument; absent that feed, use a config default
        # (0/absent => no slicing). Large F&O orders get sliced into allowed clips.
        return int(fq.get("default_clip", 0)) or 10**9

    @staticmethod
    def _slice(quantity: int, clip: int) -> list[int]:
        if clip <= 0 or quantity <= clip:
            return [quantity]
        clips = [clip] * (quantity // clip)
        if quantity % clip:
            clips.append(quantity % clip)
        return clips

    @staticmethod
    def _transient(reason: str | None) -> bool:
        r = (reason or "").lower()
        return any(k in r for k in ("network", "timeout", "timed out", "try again", "connection"))

    async def exit_price(self, position: dict) -> float | None:
        """Depth-aware exit fill (bid book when selling, ask book when buying back),
        with the same slippage entries pay — exits must not be flattered vs entries.
        Returns None when no quote is available (caller picks the fallback)."""
        inst = await get_instrument(position["instrument_token"]) or {}
        side = "SELL" if position["side"] == "BUY" else "BUY"
        return await self.sim.fill_price(
            {"exchange": inst.get("exchange", "NSE"), "tradingsymbol": position["tradingsymbol"]},
            side, int(position["quantity"]))

    async def market_exit(self, position: dict):
        # P0#3: derive the exit order from the POSITION (product/exchange persisted
        # at entry), never hardcode MIS. Unsupported/missing => fail closed (no order).
        inst = await get_instrument(position["instrument_token"]) or {}
        side = "SELL" if position["side"] == "BUY" else "BUY"
        product = position.get("product")
        exchange = position.get("exchange") or inst.get("exchange")
        variety = position.get("variety") or "regular"
        if not exit_product_supported(exchange, product):
            raise UnsafeLiveState(
                f"cannot exit {position.get('tradingsymbol')}: unsupported exchange/product "
                f"{exchange}/{product}")
        return await self.governor.call(
            "order", self.adapter.place_order, variety=variety, exchange=exchange,
            tradingsymbol=position["tradingsymbol"], transaction_type=side,
            quantity=int(position["quantity"]), product=product, order_type="MARKET")

    # --- entry -----------------------------------------------------------
    async def execute(self, decision: Decision, force_fill_qty: int | None = None) -> ExecutionResult:
        mode = await self.current_mode()
        if await get_state("engine_halted", False):
            return ExecutionResult(OrderOutcome.REJECTED, decision, reason="engine halted (fail-safe active)")
        if await get_state("kill_switch_active", False):
            return ExecutionResult(OrderOutcome.REJECTED, decision, reason="kill-switch active")
        if mode == "live":
            return await self._execute_live(decision)
        return await self._execute_sim(decision, force_fill_qty)

    async def _execute_sim(self, decision: Decision, force_fill_qty: int | None = None) -> ExecutionResult:
        fill = await self.sim.simulate(decision, fill_qty=force_fill_qty)
        if not fill:
            return ExecutionResult(OrderOutcome.REJECTED, decision, reason="no live price for simulated fill")
        pid = await self.book.open_position(decision, fill, "simulated_fill")
        outcome = OrderOutcome.PARTIAL if (force_fill_qty and force_fill_qty < decision.quantity) else OrderOutcome.FILLED
        await self.book.persist_order_fill(decision, fill, "simulated_fill", outcome)
        bracket = await create_bracket(self, decision, fill, pid, "simulated_fill")
        return ExecutionResult(outcome, decision, filled_quantity=fill.quantity, avg_price=fill.price,
                               fees_total=fill.fees["total"], position_id=pid, bracket=bracket)

    async def _poll_order(self, order_id: str, attempts: int = 12, delay: float = 0.5) -> dict:
        hist: list[dict] = []
        for _ in range(attempts):
            hist = await self.governor.call("other", self.adapter.order_history, order_id)
            last = hist[-1] if hist else {}
            status = last.get("status")
            if status in ("COMPLETE", "REJECTED", "CANCELLED"):
                return {"status": status, "filled": int(last.get("filled_quantity", 0)),
                        "avg_price": float(last.get("average_price") or 0),
                        "reason": last.get("status_message")}
            await asyncio.sleep(delay)
        last = hist[-1] if hist else {}
        return {"status": "PARTIAL", "filled": int(last.get("filled_quantity", 0)),
                "avg_price": float(last.get("average_price") or 0), "reason": "poll timeout"}

    async def _execute_live(self, decision: Decision) -> ExecutionResult:
        # P0#3: never open what we can't exit — reject unsupported exchange/product
        # BEFORE sending any broker order.
        exch = decision.instrument.get("exchange")
        if not exit_product_supported(exch, decision.product):
            log.error("entry_unsupported_product", exchange=exch, product=decision.product)
            return ExecutionResult(OrderOutcome.REJECTED, decision,
                                   reason=f"unsupported exchange/product for live: {exch}/{decision.product}")
        clips = self._slice(decision.quantity, self._freeze_limit(decision.instrument))
        filled, notional, order_ids = 0, 0.0, []
        for clip in clips:
            try:
                oid = await self.governor.call(
                    "order", self.adapter.place_order, variety="regular",
                    exchange=decision.instrument["exchange"], tradingsymbol=decision.instrument["tradingsymbol"],
                    transaction_type=decision.side, quantity=clip, product=decision.product,
                    order_type=decision.order_type,
                    price=(decision.entry_price if decision.order_type == "LIMIT" else None))
                order_ids.append(oid)
                st = await self._poll_order(oid)
                filled += st["filled"]
                notional += st["filled"] * (st["avg_price"] or 0.0)  # quantity-weighted
                if st["status"] == "REJECTED" and not self._transient(st["reason"]):
                    log.error("order_rejected_no_retry", reason=st["reason"])
                    break  # reason-aware: don't blindly retry margin/circuit/ban/freeze
            except Exception as exc:
                log.error("place_order_error", error=str(exc))
                break
        if filled == 0:
            return ExecutionResult(OrderOutcome.REJECTED, decision,
                                   reason="no fill (rejected/failed); remainder cancelled",
                                   broker_order_id=order_ids[0] if order_ids else None)
        # Quantity-weighted average fill across all clips (not just the last clip).
        avg_price = round(notional / filled, 2) if filled else 0.0
        seg = self.cost.segment_key(decision.sleeve, decision.instrument.get("instrument_type"))
        fees = self.cost.compute_leg(seg, decision.side, filled, avg_price)
        fill = Fill(quantity=filled, price=avg_price, fees=fees, ts=now_ist())
        pid = await self.book.open_position(decision, fill, "live")
        outcome = OrderOutcome.PARTIAL if filled < decision.quantity else OrderOutcome.FILLED
        await self.book.persist_order_fill(decision, fill, "live", outcome,
                                           broker_order_id=order_ids[0] if order_ids else None)
        bracket = await create_bracket(self, decision, fill, pid, "live")  # sized to `filled`
        return ExecutionResult(outcome, decision, filled_quantity=filled, avg_price=avg_price,
                               fees_total=fees["total"], position_id=pid, bracket=bracket,
                               broker_order_id=order_ids[0] if order_ids else None)

    # --- exit / guard-driven close --------------------------------------
    async def _cancel_bracket(self, pos: dict) -> None:
        """Cancel a resting live GTT-OCO bracket so it can't re-fire into a new
        naked position after the position is closed."""
        if self.mode != "live":
            return
        raw = pos.get("raw") or {}
        if isinstance(raw, str):
            import json
            raw = json.loads(raw)
        gtt_id = (raw.get("bracket") or {}).get("gtt_id")
        if not gtt_id:
            return
        try:
            await self.governor.call("order", self.adapter.delete_gtt, gtt_id)
            log.info("gtt_bracket_cancelled", id=pos.get("id"), gtt_id=gtt_id)
        except Exception as exc:
            log.error("gtt_cancel_failed", id=pos.get("id"), gtt_id=gtt_id, error=str(exc))

    async def close(self, position_id: int, reason: str, price: float | None = None,
                    fallback_price: float | None = None) -> float | None:
        """Close a position. Fill price resolution: explicit `price` (a genuinely traded
        tick from the fast-loop guards) -> spread-crossed live quote with slippage ->
        `fallback_price` (e.g. the structure's last mark) -> entry price as last resort
        (a forced exit must never be left open for lack of a quote)."""
        await self.current_mode()   # P0#1: refresh mode (guard-driven exits skip execute())
        row = await fetchrow("SELECT * FROM positions WHERE id=$1", position_id)
        if not row or row["status"] != "open":
            return None
        pos = dict(row)
        px = price or await self.exit_price(pos) or fallback_price or float(pos["average_price"])
        # Cost segment from the actual instrument type — option exits must be charged
        # option rates (STT on premium etc.), not the futures schedule.
        inst = await get_instrument(pos["instrument_token"]) or {}
        seg = self.cost.segment_key(pos["sleeve"], inst.get("instrument_type"))
        exit_side = "SELL" if pos["side"] == "BUY" else "BUY"
        fees = self.cost.compute_leg(seg, exit_side, int(pos["quantity"]), px)
        if self.mode == "live":
            # Cancel the resting OCO FIRST so the broker can't fill it after our exit.
            await self._cancel_bracket(pos)
            try:
                await self.market_exit(pos)
            except Exception as exc:
                log.error("market_exit_failed", id=position_id, error=str(exc))
        realized = await self.book.close_position(position_id, px, fees, reason)
        self.guards.disarm(position_id)
        self._last_persist.pop(position_id, None)
        # Re-entry cooldown so the same instrument can't be reopened next cycle (churn).
        try:
            cd = float(getattr(self.config.risk, "reentry_cooldown_minutes", 0) or 0)
            tok = pos.get("instrument_token")
            if cd and tok is not None:
                from common.cooldown import set_cooldown
                await set_cooldown(f"eq:{tok}", cd)
        except Exception:
            pass
        return realized

    async def on_price(self, position_id: int, price: float) -> ExecutionResult | None:
        """Fast-loop hook (Phase 5 drives this per tick): check guards, exit on a hit."""
        signal = self.guards.process(position_id, price)
        if signal is None:
            # Throttle the durable write; refresh Redis LTP cheaply on every tick.
            now = time.monotonic()
            if now - self._last_persist.get(position_id, 0.0) >= self._persist_interval:
                self._last_persist[position_id] = now
                await self.book.update_unrealized(position_id, price)
            else:
                await self.book.touch_ltp(position_id, price)
            return None
        # Disarm SYNCHRONOUSLY before awaiting close() so a concurrent tick for the
        # same instrument can't trigger a second exit while close() is in flight.
        self.guards.disarm(position_id)
        realized = await self.close(position_id, signal.reason, price=signal.price)
        log.info("guard_exit", id=position_id, reason=signal.reason, price=signal.price, realized=realized)
        return realized

    async def execute_structure(self, name: str, expiry, structure: dict, lots: int, lot_size: int,
                                strike_step: float, correlation_id: str, signal_id: int | None = None) -> dict:
        """Open a multi-leg defined-risk F&O structure (sim only for now). Live
        multi-leg placement is refused rather than half-executed."""
        if await get_state("engine_halted", False):
            return {"outcome": "REJECTED", "reason": "engine halted", "correlation_id": correlation_id}
        if await get_state("kill_switch_active", False):
            return {"outcome": "REJECTED", "reason": "kill-switch active", "correlation_id": correlation_id}
        block = live_structures_block_reason(
            await self.current_mode(),
            bool(getattr(self.config.execution, "fno_live_structures_enabled", False)))
        if block:
            log.warning("structure_live_blocked", reason=block)
            return {"outcome": "REJECTED", "reason": block, "correlation_id": correlation_id}
        return await open_structure(self, name, expiry, structure, lots, lot_size, strike_step,
                                    correlation_id, signal_id)

    async def adopt_open_positions(self) -> dict:
        await self.current_mode()
        return await adopt_open_positions(self)


def build_executor(config, adapter, governor, alerter=None) -> Executor:
    cost = CostModel(config.execution.cost_model)
    return Executor(
        config=config, adapter=adapter, governor=governor,
        book=PositionBook(alerter), cost_model=cost,
        simulator=FillSimulator(config, cost, adapter, governor),
        guards=GuardManager(), alerter=alerter,
    )
