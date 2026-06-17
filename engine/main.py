"""Engine process entrypoint.

Phase 0: bootstrap infra (config, DB, Redis), ensure the Kite token, schedule the
daily token refresh.
Phase 1: start the market-data service (instruments master, historical backfill,
live KiteTicker feed + candle aggregation + gap reconciliation) and schedule the
daily instruments refresh + nightly backfill.

The fast/slow trading loops arrive in later phases. Bootstrap is fail-safe:
missing creds or a failed dependency logs and continues rather than crashing.
"""
from __future__ import annotations

import asyncio
import signal
from datetime import datetime, time as dtime, timedelta

from apscheduler.triggers.cron import CronTrigger

from broker.kite_adapter import KiteAdapter
from broker.scheduler import build_scheduler
from common.alerts import Alerter
from common.commands import claim_commands, complete_command, fail_command, recover_stuck_commands
from common.cooldown import in_cooldown
from common.db import close_pool, fetch, fetchval, init_pool
from common.events import publish_event
from common.logging import configure_logging, get_logger
from common.market_time import IST, is_within, now_ist
from common.redis_client import close_redis, get_redis
from common.state import get_state, set_state
from config.loader import get_config
from config.settings import get_settings
from data.historical import incremental_backfill
from data.instruments import get_instrument, get_token
from data.service import MarketDataService
from engine.confidence import ConfidenceModel
from engine.context_builder import build_fno_context, build_intraday_context
from engine.orchestrator import DecisionOrchestrator
from execution.executor import build_executor
from execution.failsafe import safe_exit_all
from execution.recovery import adopt_open_positions
from execution.structures import close_structure, mark_structures
from llm.context import LLMContextLayer
from risk.capital import CapitalReader
from risk.circuits import (drawdown_breached, loss_streak_hit, period_loss_breached,
                           profit_lock_breached, should_disable_sleeve)
from risk.engine import RiskEngine
from risk.kill_switch import KillSwitch
from strategies.fno import FnoPipeline
from strategies.intraday import IntradayPipeline
from strategies.mcx import McxIntradayPipeline
from strategies.swing import SwingPipeline

log = get_logger("engine")


def _make_ltp_handler(executor):
    """Fast loop (spec §1): per-tick, drive the guards of any open position on that
    instrument. Pure price checks — no pipelines, no LLM, no blocking work."""
    async def on_ltp(ltp_map: dict) -> None:
        for tok_s, price in ltp_map.items():
            try:
                token, px = int(tok_s), float(price)
            except (TypeError, ValueError):
                continue
            for pid in executor.guards.for_token(token):
                try:
                    await executor.on_price(pid, px)
                except Exception as exc:
                    log.error("fast_loop_on_price_error", position_id=pid, error=str(exc))
    return on_ltp


def _build_trading_stack(cfg, settings, adapter, md_service, alerter):
    """Assemble the Phase 2-5 trading components, sharing the market-data governor."""
    executor = build_executor(cfg, adapter, md_service.governor, alerter)
    # paper-mode overlay (config) — static capital + paper risk %, still simulated_fill
    paper = float(getattr(cfg.risk, "paper_capital", 0) or 0)
    pt = float(getattr(cfg.risk, "paper_per_trade_pct", 0) or 0) if paper > 0 else 0
    dl = float(getattr(cfg.risk, "paper_daily_max_loss_pct", 0) or 0) if paper > 0 else 0
    from common.runtime_mode import get_runtime_mode
    capital_reader = CapitalReader(adapter, md_service.governor,
                                   static_capital=(paper if paper > 0 else None),
                                   compound=bool(getattr(cfg.risk, "paper_compound", False)),
                                   mode_provider=get_runtime_mode)   # P0#1: live -> broker capital
    kill_switch = KillSwitch(cfg, cfg.execution.mode, alerter, daily_loss_pct=(dl or None))
    risk = RiskEngine(
        cfg, capital_reader=capital_reader, kill_switch=kill_switch,
        adapter=adapter, governor=md_service.governor, alerter=alerter,
        mode=cfg.execution.mode, per_trade_pct=(pt or None),
    )
    if paper > 0:
        log.info("paper_mode_active", capital=paper,
                 per_trade_pct=pt or cfg.risk.per_trade_risk_pct.default,
                 daily_max_loss_pct=dl or cfg.risk.daily_max_loss_pct.default)
    pipelines = {
        "intraday_stocks": IntradayPipeline(cfg),
        "swing_stocks": SwingPipeline(cfg),
        "fno": FnoPipeline(cfg),
        "mcx_commodities": McxIntradayPipeline(cfg),
    }
    llm = LLMContextLayer(cfg, settings)
    orchestrator = DecisionOrchestrator(cfg, pipelines, ConfidenceModel(cfg), risk, executor, llm, alerter)
    return executor, risk, orchestrator


async def _ensure_vix_history(md_service) -> None:
    """INDIA VIX daily history backs the F&O IV-rank proxy. Best-effort, once."""
    try:
        tok = await get_token("NSE:INDIA VIX")
        if tok:
            await incremental_backfill(md_service.adapter, md_service.governor, tok, "day", 300, 200)
            log.info("vix_history_ready")
    except Exception as exc:
        log.warning("vix_history_failed", error=str(exc))


async def _update_killswitch(risk, executor) -> None:
    """Recompute the day's realized+unrealized P&L, push it into daily_pnl, then let
    the kill switch evaluate the daily max-loss line. On a fresh trip, flatten."""
    start = now_ist().replace(hour=0, minute=0, second=0, microsecond=0)
    # P1#8: scope the kill-switch P&L to the ACTIVE namespace (paper P&L must not
    # feed a live kill-switch, and vice-versa).
    from common.runtime_mode import get_runtime_mode
    from risk.scope import position_scope, where_clause
    frag, sargs = where_clause(position_scope(await get_runtime_mode()), start_idx=2)
    rows = await fetch(f"SELECT status, COALESCE(realized_pnl,0) rp, COALESCE(unrealized_pnl,0) up "
                       f"FROM positions WHERE {frag} AND ((status='closed' AND closed_at>=$1) OR status='open')",
                       start, *sargs)
    realized = sum(float(x["rp"]) for x in rows if x["status"] == "closed")
    unrealized = sum(float(x["up"]) for x in rows if x["status"] == "open")
    await risk.kill_switch.update_pnl(realized=realized, unrealized=unrealized)
    st = await risk.check_kill_switch()
    if st.active and st.tripped_today and risk.kill_switch.flatten_on_trip:
        if not await get_state("engine_halted", False):  # flatten once, on the fresh trip
            for g in list(executor.structures.all()):
                await close_structure(executor, g, "killswitch_flatten", force=True)
            await safe_exit_all(executor, "kill-switch: daily max-loss breached")


async def _update_brakes(cfg, risk, executor) -> None:
    """Period + activity brakes (block NEW entries only; open positions stay managed).
    - weekly/monthly realized-loss brakes: latched for the rest of the period, auto-
      reset when the week/month rolls (the daily kill-switch can't stop a slow bleed).
    - daily trade budget: structures count once (correlation_id), not per leg.
    - per-sleeve loss-streak: N straight losing trades today stands that sleeve down
      until tomorrow. Enforced by the Risk Engine on every sizing call."""
    capital = await risk.capital.get_capital()
    if capital <= 0:
        return
    today = now_ist().date()
    day_start = datetime.combine(today, dtime.min, tzinfo=IST)
    pb = getattr(cfg.risk, "period_brakes", {}) or {}
    tb = getattr(cfg.risk, "trade_brakes", {}) or {}

    # --- weekly / monthly realized-loss brakes (latched per period) ------------
    iso = today.isocalendar()
    week_key, month_key = f"{iso.year}-W{iso.week:02d}", f"{today.year}-{today.month:02d}"
    state = await get_state("period_brake_active")
    if state and state.get("period") not in (week_key, month_key):
        await set_state("period_brake_active", None, "risk")   # period rolled -> release
        state = None
    if not state:
        checks = (("month", today.replace(day=1), month_key,
                   float(pb.get("monthly_max_loss_pct", 0) or 0)),
                  ("week", today - timedelta(days=today.weekday()), week_key,
                   float(pb.get("weekly_max_loss_pct", 0) or 0)))
        for scope, start, key, pct in checks:
            if pct <= 0:
                continue
            realized = float(await fetchval(
                "SELECT COALESCE(SUM(realized_pnl),0) FROM positions "
                "WHERE status='closed' AND closed_at >= $1",
                datetime.combine(start, dtime.min, tzinfo=IST)) or 0)
            if period_loss_breached(realized, capital, pct):
                await set_state("period_brake_active",
                                {"scope": scope, "period": key,
                                 "realized": round(realized, 2), "limit_pct": pct}, "risk")
                msg = (f"{scope.upper()} BRAKE: realized Rs {realized:,.0f} breached "
                       f"-{pct}% of Rs {capital:,.0f}. New entries blocked until the "
                       f"{scope} rolls ({key}). Open positions stay managed.")
                log.error("period_brake_tripped", scope=scope, realized=round(realized, 2), limit_pct=pct)
                if executor.alerter:
                    await executor.alerter.send_async(f"{scope.title()} drawdown brake tripped", msg)
                await publish_event("alert", {"kind": "period_brake", "message": msg, "severity": "critical"})
                break

    # --- daily trade budget ------------------------------------------------------
    max_trades = int(tb.get("max_trades_per_day", 0) or 0)
    flag = await get_state("trade_budget_exhausted")
    if flag and flag.get("date") != str(today):
        await set_state("trade_budget_exhausted", None, "risk")
        flag = None
    if max_trades and not flag:
        n = int(await fetchval(
            "SELECT COUNT(DISTINCT correlation_id) FROM positions WHERE opened_at >= $1",
            day_start) or 0)
        if n >= max_trades:
            await set_state("trade_budget_exhausted", {"date": str(today), "trades": n}, "risk")
            log.error("trade_budget_exhausted", trades=n, budget=max_trades)
            if executor.alerter:
                await executor.alerter.send_async(
                    "Daily trade budget exhausted",
                    f"{n} trades today >= budget {max_trades}. No new entries until tomorrow.")

    # --- per-sleeve loss streak (today, per TRADE not per leg) --------------------
    max_losses = int(tb.get("max_consecutive_losses", 0) or 0)
    if max_losses:
        rows = await fetch(
            "SELECT sleeve, SUM(realized_pnl) AS pnl, MAX(closed_at) AS ca FROM positions "
            "WHERE status='closed' AND closed_at >= $1 GROUP BY sleeve, correlation_id "
            "ORDER BY ca DESC", day_start)
        per_sleeve: dict[str, list[float]] = {}
        for r in rows:
            per_sleeve.setdefault(r["sleeve"] or "?", []).append(float(r["pnl"]))
        for sleeve, pnls in per_sleeve.items():
            key = f"sleeve_{sleeve}_brake"
            sflag = await get_state(key)
            if sflag and sflag.get("date") != str(today):
                await set_state(key, None, "risk")
                sflag = None
            if not sflag and loss_streak_hit(pnls, max_losses):
                await set_state(key, {"date": str(today), "streak": max_losses}, "risk")
                log.error("sleeve_loss_streak_brake", sleeve=sleeve, streak=max_losses)
                if executor.alerter:
                    await executor.alerter.send_async(
                        "Loss-streak brake",
                        f"{sleeve}: {max_losses} consecutive losing trades today — "
                        "sleeve stands down until tomorrow.")


async def _update_circuits(cfg, risk, executor) -> None:
    """Soft circuits (Phase 3.2): max-drawdown circuit (block new entries) + per-sleeve
    auto-disable on negative rolling expectancy. Neither flattens — that's the kill
    switch. Returns nothing; sets config_state flags the slow loop honours."""
    capital = await risk.capital.get_capital()
    if capital <= 0:
        return
    start = now_ist().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = await fetch("SELECT status, COALESCE(realized_pnl,0) rp, COALESCE(unrealized_pnl,0) up "
                       "FROM positions WHERE (status='closed' AND closed_at>=$1) OR status='open'", start)
    day_net = (sum(float(r["rp"]) for r in rows if r["status"] == "closed")
               + sum(float(r["up"]) for r in rows if r["status"] == "open"))

    # max-drawdown circuit: track the day's peak net P&L in config_state.
    today = now_ist().date().isoformat()
    peak_state = await get_state("dd_peak", {}) or {}
    peak = float(peak_state.get("peak", 0.0)) if peak_state.get("date") == today else 0.0
    peak = max(peak, day_net, 0.0)
    await set_state("dd_peak", {"date": today, "peak": peak})
    max_dd = float(getattr(cfg.risk, "max_drawdown_pct", 0) or 0)
    plock = getattr(cfg.risk, "profit_lock", {}) or {}
    dd_hit = drawdown_breached(peak, day_net, capital, max_dd)
    pl_hit = profit_lock_breached(peak, day_net, capital,
                                  float(plock.get("trigger_pct", 0) or 0),
                                  float(plock.get("max_giveback_pct", 40) or 40))
    if (dd_hit or pl_hit) and not await get_state("dd_circuit_active", False):
        await set_state("dd_circuit_active", True, "risk")
        kind = "profit_lock" if (pl_hit and not dd_hit) else "max_drawdown"
        log.error("dd_circuit_tripped", kind=kind, peak=round(peak, 2), current=round(day_net, 2), capital=capital)
        msg = (f"Circuit ({kind}): gave back ₹{peak - day_net:.0f} from peak ₹{peak:.0f}. "
               "New entries blocked until reset (open positions stay managed).")
        if executor.alerter:
            await executor.alerter.send_async("Drawdown circuit tripped", msg)
        try:
            await publish_event("alert", {"kind": "dd_circuit", "message": msg, "severity": "critical"})
        except Exception:
            pass

    # per-sleeve auto-disable on negative rolling expectancy.
    guard = getattr(cfg.risk, "strategy_guard", {}) or {}
    lookback = int(guard.get("lookback_trades", 20))
    min_trades = int(guard.get("min_trades", 10))
    floor = float(guard.get("expectancy_floor", -0.2))
    for sleeve in ("intraday_stocks", "fno", "swing_stocks", "mcx_commodities"):
        if not await get_state(f"sleeve_{sleeve}_enabled", True):
            continue
        # Per-TRADE R-multiples: a structure's legs aggregate to one (P&L / risk) pair,
        # so the expectancy window is `lookback` trades — not an arbitrary mix of legs.
        trows = await fetch(
            "SELECT SUM(realized_pnl) AS rp, SUM(r_rupees) AS rr FROM positions "
            "WHERE sleeve=$1 AND status='closed' AND r_rupees>0 "
            "GROUP BY COALESCE(correlation_id::text, id::text) "
            "ORDER BY MAX(closed_at) DESC LIMIT $2", sleeve, lookback)
        rmults = [float(r["rp"]) / float(r["rr"]) for r in trows if r["rr"] and float(r["rr"]) > 0]
        if should_disable_sleeve(rmults, min_trades, floor):
            await set_state(f"sleeve_{sleeve}_enabled", False, "risk")
            exp = sum(rmults) / len(rmults)
            log.error("sleeve_auto_disabled", sleeve=sleeve, expectancy=round(exp, 3), n=len(rmults))
            if executor.alerter:
                await executor.alerter.send_async(
                    "Sleeve auto-disabled",
                    f"{sleeve} expectancy {exp:.2f}R over last {len(rmults)} trades — new entries disabled.")


async def _check_kill_criteria(cfg, executor) -> None:
    """Tier-3 kill criteria, written in advance and enforced by the machine: once a
    sleeve has `review_min_trades` lifetime closed trades, a lifetime expectancy below
    `review_expectancy_floor` is a VERDICT — the sleeve is disabled and stays down
    until a human reviews it. The rolling 20-trade guard catches acute bleeding;
    this catches the slow grind that day-to-day noise hides."""
    guard = getattr(cfg.risk, "strategy_guard", {}) or {}
    min_trades = int(guard.get("review_min_trades", 0) or 0)
    floor = float(guard.get("review_expectancy_floor", -0.1))
    if min_trades <= 0:
        return
    for sleeve in ("intraday_stocks", "fno", "swing_stocks", "mcx_commodities"):
        if not await get_state(f"sleeve_{sleeve}_enabled", True):
            continue
        rows = await fetch(
            "SELECT SUM(realized_pnl) AS rp, SUM(r_rupees) AS rr FROM positions "
            "WHERE sleeve=$1 AND status='closed' AND r_rupees>0 "
            "GROUP BY COALESCE(correlation_id::text, id::text)", sleeve)
        rmults = [float(r["rp"]) / float(r["rr"]) for r in rows if r["rr"] and float(r["rr"]) > 0]
        if len(rmults) < min_trades:
            continue
        exp = sum(rmults) / len(rmults)
        if exp < floor:
            await set_state(f"sleeve_{sleeve}_enabled", False, "kill_criteria")
            await set_state(f"sleeve_{sleeve}_review_required", True, "kill_criteria")
            msg = (f"KILL CRITERIA MET: {sleeve} lifetime expectancy {exp:+.3f}R over "
                   f"{len(rmults)} trades is below the pre-committed floor {floor}R. "
                   "Sleeve disabled. It stays down until you review it — do not "
                   "re-enable on a feeling.")
            log.error("kill_criteria_met", sleeve=sleeve, expectancy=round(exp, 3), n=len(rmults))
            if executor.alerter:
                await executor.alerter.send_async(f"KILL CRITERIA: {sleeve} disabled", msg)
            await publish_event("alert", {"kind": "kill_criteria", "message": msg, "severity": "critical"})


async def _is_monthly_expiry_today(name: str = "NIFTY") -> bool:
    """True when TODAY is the underlying's MONTHLY expiry (its last expiry of the
    month). The final hours of monthly expiry trade on pinning/dealer flows."""
    try:
        from data.option_chain import list_expiries
        exps = await list_expiries(name)
        today = now_ist().date()
        if today not in exps:
            return False
        return not any(e.year == today.year and e.month == today.month and e > today
                       for e in exps)
    except Exception as exc:
        log.warning("monthly_expiry_check_failed", error=str(exc))
        return False


async def _manage_loop(cfg, risk, executor, md_service) -> None:
    """ALWAYS-ON risk management (independent of the decision chain): mark open F&O
    structures (book/stop on combined P&L) and keep the daily P&L + kill switch
    evaluated — even when the orchestrator is disabled, paused, or the dd-circuit is
    active. Pausing decisions must never pause stop-loss monitoring on open risk.
    Also enforces expiry-day discipline: on monthly index expiry, intraday equity is
    flattened by 14:30 (the pinning hours are a different, hostile regime)."""
    await asyncio.sleep(15)
    market = (cfg.data.feed or {}).get("market_window", ["09:15", "15:30"])
    # P1#10: keep managing open risk whenever ANY venue is open (covers the MCX
    # evening session, not just the equity window).
    from common.sessions import MarketSessions
    sessions = MarketSessions()
    ks_day = None
    monthly_expiry = False
    eq_flattened = False
    while True:
        try:
            if not sessions.any_open():
                await asyncio.sleep(60); continue
            today = now_ist().date()
            if ks_day != today:
                cap_now = await risk.capital.get_capital(refresh=True)
                if cap_now > 0:
                    await risk.kill_switch.ensure_daily_row(cap_now)
                    monthly_expiry = await _is_monthly_expiry_today()
                    eq_flattened = False
                    if monthly_expiry:
                        log.info("monthly_expiry_today_equity_flatten_at_1430")
                    await _check_kill_criteria(cfg, executor)   # once per day
                    ks_day = today
            try:
                for m in await mark_structures(executor, md_service.adapter, md_service.governor):
                    if m.get("action") in ("STOP", "TARGET"):
                        log.info("structure_exit", **m)
            except Exception as exc:
                log.error("mark_structures_error", error=str(exc))
            await _update_killswitch(risk, executor)
            await _update_brakes(cfg, risk, executor)
            # Monthly-expiry early exit for intraday equity (before pinning hours).
            if monthly_expiry and not eq_flattened and now_ist().time() >= dtime(14, 30):
                try:
                    for p in await executor.book.get_open():
                        if p.get("sleeve") == "intraday_stocks":
                            await executor.close(p["id"], "expiry_day_early_exit")
                    eq_flattened = True
                    log.info("expiry_day_equity_flattened")
                except Exception as exc:
                    log.error("expiry_flatten_error", error=str(exc))
        except Exception as exc:
            log.error("manage_loop_error", error=str(exc))
        await asyncio.sleep(30)


async def _slow_loop(cfg, orchestrator, risk, md_service) -> None:
    """Slow loop (spec §1): the DECISION chain on the candle-close cadence — run
    intraday equity + the F&O universe through gates -> confidence -> risk -> LLM ->
    execution. Gated by the `orchestrator_enabled` operator flag (default off),
    capital, pause/halt/kill-switch/dd-circuit state. Risk management of OPEN
    positions lives in _manage_loop and keeps running when this loop is gated off."""
    await asyncio.sleep(30)  # let backfill + feed settle
    market = (cfg.data.feed or {}).get("market_window", ["09:15", "15:30"])
    fno_universe = (cfg.data.universe or {}).get("fno", [])
    vix_done = False
    executor = orchestrator.executor
    while True:
        try:
            if not is_within(market[0], market[1]):
                await asyncio.sleep(60); continue
            if not await get_state("orchestrator_enabled", False):
                await asyncio.sleep(60); continue
            if (await get_state("engine_paused", False) or await get_state("engine_halted", False)
                    or await get_state("kill_switch_active", False)
                    or await get_state("dd_circuit_active", False)):
                await asyncio.sleep(30); continue
            cap_now = await risk.capital.get_capital(refresh=True)
            if cap_now <= 0:
                await asyncio.sleep(120); continue  # unfunded -> nothing to size
            await _update_circuits(cfg, risk, executor)
            if await get_state("dd_circuit_active", False):
                await asyncio.sleep(30); continue
            if not vix_done:
                await _ensure_vix_history(md_service)
                vix_done = True

            # 2. intraday equity — "Stocks in Play" selection (Zarattini/Barbon/Aziz):
            # build context for the whole universe, compute LIVE day breadth (% of
            # universe above VWAP), then run only the top-N highest-RVOL names through
            # the decision chain. The documented ORB alpha is in SELECTION (top
            # relative-volume names), not in the breakout pattern itself.
            if await get_state("sleeve_intraday_stocks_enabled", True):
                ip = cfg.strategy.intraday_stocks or {}
                candidates = []
                for token in list(md_service.tokens or []):
                    try:
                        inst = await get_instrument(token)
                        if not inst or inst.get("segment") == "INDICES" or inst.get("instrument_type") != "EQ":
                            continue
                        if await in_cooldown(f"eq:{token}"):
                            continue   # recently exited -> avoid churn re-entry
                        ctx = await build_intraday_context(token, regime_cfg=ip.get("regime"))
                        if ctx is not None:
                            candidates.append((token, inst, ctx))
                    except Exception as exc:
                        log.error("intraday_ctx_error", token=token, error=str(exc))

                # Live day-type from the freshly built contexts: % above VWAP.
                bg = ip.get("breadth_gate", {}) or {}
                day_breadth = "unknown"
                if candidates:
                    above = sum(1 for _, _, c in candidates if c.vwap > 0 and c.last_price >= c.vwap)
                    pct = above / len(candidates) * 100.0
                    if pct >= float(bg.get("bullish_min_pct", 60) or 60):
                        day_breadth = "bullish"
                    elif pct <= float(bg.get("bearish_max_pct", 40) or 40):
                        day_breadth = "bearish"
                    else:
                        day_breadth = "mixed"
                for _, _, c in candidates:
                    c.day_breadth = day_breadth   # engine stamps it fresh every cycle

                top_n = int((ip.get("stocks_in_play") or {}).get("top_n", 0) or 0)
                if top_n > 0 and len(candidates) > top_n:
                    candidates.sort(key=lambda t: t[2].rvol, reverse=True)
                    candidates = candidates[:top_n]

                for token, inst, ctx in candidates:
                    try:
                        res = await asyncio.wait_for(
                            orchestrator.evaluate("intraday_stocks", inst, ctx), timeout=45)
                        if res.get("status") not in (None, "skip"):
                            log.info("orchestrator_decision", sleeve="intraday", symbol=inst.get("tradingsymbol"),
                                     status=res.get("status"), outcome=res.get("outcome"), confidence=res.get("confidence"))
                    except Exception as exc:
                        log.error("intraday_eval_error", token=token, error=str(exc))

            # 3. F&O universe (one open structure per underlying; per-sleeve toggle).
            # P0#6: in live, skip F&O entirely unless live structures are enabled
            # (they aren't implemented for real orders) — don't even build contexts.
            _mode_now = await get_state("execution_mode", cfg.execution.mode)
            _fno_live_ok = not (_mode_now == "live"
                                and not bool(getattr(cfg.execution, "fno_live_structures_enabled", False)))
            if _fno_live_ok and await get_state("sleeve_fno_enabled", True):
                open_names = {g.name for g in executor.structures.all()}
                for entry in fno_universe:
                    try:
                        name, ukey = entry.get("name"), entry.get("underlying")
                        if not name or not ukey or name in open_names:
                            continue
                        if await in_cooldown(f"fno:{name}"):
                            continue   # recently exited this underlying -> cooldown
                        utok = await get_token(ukey)
                        if not utok:
                            continue
                        ctx = await build_fno_context(md_service.adapter, md_service.governor, name, ukey, utok, cfg.strategy.fno)
                        if ctx is None:
                            continue
                        inst = {"tradingsymbol": name, "exchange": "NFO", "instrument_type": "CE", "lot_size": ctx.lot_size}
                        res = await asyncio.wait_for(orchestrator.evaluate("fno", inst, ctx), timeout=45)
                        if res.get("status") not in (None, "skip"):
                            log.info("orchestrator_decision", sleeve="fno", name=name, status=res.get("status"),
                                     structure=res.get("structure"), lots=res.get("lots"), max_loss=res.get("max_loss"))
                    except Exception as exc:
                        log.error("fno_eval_error", name=entry.get("name"), error=str(exc))

            # 3b. MCX commodities — front-month futures through the intraday-style
            # pipeline (no sector filter; 23:15 hard square-off armed on each guard).
            if await get_state("sleeve_mcx_commodities_enabled", True):
                mcx_cfg = cfg.strategy.mcx_commodities or {}
                win = (mcx_cfg.get("intraday") or {}).get("entry_window", {}) or {}
                in_window = is_within(win.get("start", "09:30"), win.get("end", "15:00"))
                for name, inst in (getattr(md_service, "mcx_front", {}) or {}).items():
                    try:
                        token = int(inst["instrument_token"])
                        if not in_window or await in_cooldown(f"eq:{token}"):
                            continue
                        ctx = await build_intraday_context(token, regime_cfg=(cfg.strategy.intraday_stocks or {}).get("regime"))
                        if ctx is None:
                            continue
                        ctx.now_window_ok = True          # MCX session, not the equity window
                        ctx.day_breadth = "unknown"       # equity breadth doesn't apply (fail-open)
                        res = await asyncio.wait_for(
                            orchestrator.evaluate("mcx_commodities", dict(inst), ctx), timeout=45)
                        if res.get("status") not in (None, "skip"):
                            log.info("orchestrator_decision", sleeve="mcx", symbol=inst.get("tradingsymbol"),
                                     status=res.get("status"), outcome=res.get("outcome"), confidence=res.get("confidence"))
                    except Exception as exc:
                        log.error("mcx_eval_error", name=name, error=str(exc))

            # 4. periodic broker reconciliation (live only) — detect book drift early.
            if await executor.current_mode() == "live":
                try:
                    bp = await md_service.governor.call("other", md_service.adapter.positions)
                    net = bp.get("net", []) if isinstance(bp, dict) else []
                    from execution.reconciler import run_reconcile
                    await run_reconcile(executor, net)         # P1#11: graded reconcile + persist + act
                    await executor.resolve_pending_closes()   # P0#4: finish CLOSE_PENDING exits
                    await executor.reconcile_brackets()        # P0#7: cancel orphaned GTTs
                    await (await get_redis()).set("aegis:feed:last_reconcile", now_ist().isoformat())
                except Exception as exc:
                    log.error("reconcile_error", error=str(exc))

            await _publish_dashboard_snapshot()
        except Exception as exc:
            log.error("slow_loop_error", error=str(exc))
        await asyncio.sleep(60)


async def _publish_dashboard_snapshot() -> None:
    """Heartbeat + day-P&L push for the dashboard (Command Center is also REST-pollable)."""
    try:
        r = await get_redis()
        await r.set("aegis:engine:heartbeat", now_ist().isoformat())
        start = now_ist().replace(hour=0, minute=0, second=0, microsecond=0)
        # Realized = positions CLOSED today (regardless of when opened — overnight/swing
        # exits count today); unrealized = all currently-open positions.
        rows = await fetch("SELECT status, COALESCE(realized_pnl,0) rp, COALESCE(unrealized_pnl,0) up "
                           "FROM positions WHERE (status='closed' AND closed_at>=$1) OR status='open'", start)
        realized = sum(float(x["rp"]) for x in rows if x["status"] == "closed")
        unrealized = sum(float(x["up"]) for x in rows if x["status"] == "open")
        await publish_event("pnl_update", {"realized": round(realized, 2), "unrealized": round(unrealized, 2),
                                           "net": round(realized + unrealized, 2),
                                           "killswitch_used": round(max(0.0, -(realized + unrealized)), 2)})
    except Exception as exc:
        log.warning("dashboard_snapshot_failed", error=str(exc))


async def _command_loop(executor) -> None:
    """Drain operator commands enqueued by the API (~1s): flatten / close / modify.
    Runs regardless of feed state so the panic button always works."""
    while True:
        try:
            for cmd in await claim_commands("engine"):   # P1#12: durable claim
                cid_db = cmd.get("_id")
                try:
                    kind = cmd.get("type")
                    if kind == "flatten":
                        for g in list(executor.structures.all()):
                            await close_structure(executor, g, "operator_flatten", force=True)
                        await safe_exit_all(executor, cmd.get("reason", "operator flatten-all"))
                    elif kind == "close":
                        cid = str(cmd.get("id"))
                        if cid.isdigit():
                            await executor.close(int(cid), "operator_close")
                        else:
                            for g in [x for x in executor.structures.all() if x.correlation_id == cid]:
                                await close_structure(executor, g, "operator_close", force=True)
                    elif kind == "modify":
                        cid = str(cmd.get("id"))
                        if cid.isdigit():
                            guard = executor.guards.guards.get(int(cid))
                            if guard:
                                long = guard.side == "BUY"
                                # Validate sides: a long's stop is below entry & target above
                                # (inverted for a short). Reject fat-finger levels.
                                if cmd.get("stop") is not None:
                                    ns = float(cmd["stop"])
                                    if (ns < guard.entry) if long else (ns > guard.entry):
                                        guard.stop = ns
                                    else:
                                        log.warning("modify_rejected_bad_stop", id=cid, stop=ns,
                                                    side=guard.side, entry=guard.entry)
                                if cmd.get("target") is not None:
                                    nt = float(cmd["target"])
                                    if (nt > guard.entry) if long else (nt < guard.entry):
                                        guard.target = nt
                                    else:
                                        log.warning("modify_rejected_bad_target", id=cid, target=nt,
                                                    side=guard.side, entry=guard.entry)
                                log.info("position_modified", id=cid, stop=guard.stop, target=guard.target)
                    await complete_command(cid_db)   # P1#12: mark SUCCEEDED only after it ran
                except Exception as exc:
                    log.error("command_exec_error", id=cid_db, type=cmd.get("type"), error=str(exc))
                    await fail_command(cid_db, str(exc))   # -> RETRYING / DEAD_LETTER
        except Exception as exc:
            log.error("command_loop_error", error=str(exc))
        await asyncio.sleep(1)


async def _safe_start(md_service: MarketDataService) -> None:
    try:
        await md_service.start()
    except Exception as exc:
        log.error("market_data_start_failed", error=str(exc))


async def _daily_token_refresh(adapter, md_service) -> None:
    """Refresh the daily Kite token, then reconnect the feed with the new token."""
    try:
        await asyncio.to_thread(adapter.refresh_token)
        log.info("scheduled_token_refresh_ok")
        if md_service is not None:
            await md_service.reconnect_feed()
    except Exception as exc:
        log.error("scheduled_token_refresh_failed", error=str(exc))


async def _paper_autorun_enable() -> None:
    """Arm the slow-loop decision chain at market open (paper run). SAFETY: only
    enables when execution_mode is simulated_fill — never auto-arms live trading."""
    mode = await get_state("execution_mode", "simulated_fill")
    if mode != "simulated_fill":
        log.warning("paper_autorun_skipped_not_sim", mode=mode)
        return
    await set_state("orchestrator_enabled", True)
    log.info("paper_autorun_enabled")


async def _paper_autorun_disable() -> None:
    """Stop NEW entries at close (open positions stay managed)."""
    await set_state("orchestrator_enabled", False)
    log.info("paper_autorun_disabled")


async def _journal_job(alerter) -> None:
    """17:00 IST black-box recorder: write the day's full journal (trades, anomalies
    = bug signatures, funnel, learning status) to daily_journal + email it. The raw
    material for every periodic system review — evidence, not memory."""
    try:
        from research.journal import save_and_send
        await save_and_send(alerter)
        log.info("daily_journal_written")
    except Exception as exc:
        log.error("daily_journal_failed", error=str(exc))


async def _edge_report_job(alerter) -> None:
    """Friday-evening edge-decay email (Tier-3 process alpha): weekly per-sleeve
    expectancy trend + which features still discriminate. Edges decay as markets
    adapt — the defense is measuring yours on a schedule, not on a feeling."""
    try:
        from research.edge import build_edge_report
        report = await build_edge_report()
        if alerter:
            await alerter.send_async("Weekly edge-decay report", report)
        log.info("edge_report_sent")
    except Exception as exc:
        log.error("edge_report_failed", error=str(exc))


async def _meta_retrain_job(cfg, orchestrator) -> None:
    """Nightly meta-labeler retrain (after close): rebuild the dataset from fully
    closed trades, train on a temporal split, and activate ONLY if the model passes
    the out-of-sample validation gate — then hot-reload it into the orchestrator.
    Until a model validates, this is a no-op and trading is unaffected."""
    try:
        from api import research as research_svc
        from research.registry import load_labeler
        meta_cfg = dict(getattr(cfg.system, "meta_label", {}) or {})
        res = await research_svc.train_and_register(meta_cfg=meta_cfg)
        if res.get("error"):
            log.info("meta_retrain_skipped", reason=res["error"])
            return
        if res.get("validated"):
            orchestrator.meta_labeler = await load_labeler()
            log.info("meta_labeler_activated", id=res["id"], **res["metrics"])
        else:
            log.info("meta_model_not_validated_kept_inactive", id=res["id"],
                     accuracy=res["metrics"]["accuracy"], lift=res["metrics"]["lift"])
    except Exception as exc:
        log.error("meta_retrain_failed", error=str(exc))


async def _eod_summary(alerter) -> None:
    """Daily EOD report (spec §9): emails the running equity curve — starting capital
    (₹10L) with each day's realized P&L added/subtracted, plus a ~1-month projection —
    and pushes a short dashboard alert event."""
    try:
        from common.equity_report import build_equity_report
        rep = await build_equity_report()
        if alerter:
            await alerter.send_async(rep.subject, rep.text, html=rep.html)
        pct = (rep.balance - rep.start_capital) / rep.start_capital * 100.0 if rep.start_capital else 0.0
        short = (f"EOD: balance Rs {rep.balance:,.0f} ({pct:+.2f}% vs start), "
                 f"{rep.n_days} day(s) tracked; ~1mo projection Rs {rep.projected:,.0f}.")
        await publish_event("alert", {"kind": "eod_summary", "message": short, "severity": "info"})
        log.info("eod_summary_sent", balance=round(rep.balance, 2), projected=round(rep.projected, 2))
    except Exception as exc:
        log.error("eod_summary_failed", error=str(exc))


async def _dataplatform_ingest_job(cfg) -> None:
    """Compound the F&O history forward (Pillar 1): pull the last few sessions
    into the Parquet lake + the shared operational store (TimescaleDB when
    TIMESCALE_DSN is set). Fully isolated from the trading path — the call is
    best-effort and a failure only logs. Runs in a worker thread so the blocking
    Kite/IO pull never stalls the event loop."""
    try:
        from dataplatform.ingestion.daily import run_daily_ingestion
        dp = getattr(cfg.system, "dataplatform", {}) or {}
        res = await asyncio.to_thread(
            run_daily_ingestion,
            int(dp.get("days_back", 3) or 3),
            str(dp.get("source", "kite") or "kite"),
        )
        if res.get("error"):
            log.warning("dataplatform_ingest_skipped", reason=res.get("error"), source=res.get("source"))
        else:
            log.info("dataplatform_ingest_ok", rows=res.get("rows"), days=res.get("days"),
                     store=res.get("store_backend"))
    except Exception as exc:
        log.error("dataplatform_ingest_failed", error=str(exc))


async def _health_digest_job(alerter) -> None:
    """Email a morning health snapshot (mode/kill-switch/feed/lake/positions/P&L/
    go-live readiness) so the live system can be monitored without logging in."""
    try:
        from research.health_digest import save_and_send
        await save_and_send(alerter)
        log.info("health_digest_sent")
    except Exception as exc:
        log.error("health_digest_failed", error=str(exc))


async def _heartbeat_loop(adapter) -> None:
    """P1#13: independent liveness beacon — proves the process + its deps are alive
    regardless of whether the trading loops are gated on/off. Publishes a richer
    doc to aegis:engine:liveness and keeps the legacy heartbeat key fresh."""
    import json as _json
    while True:
        doc = {"ts": now_ist().isoformat(), "loop": "alive"}
        try:
            await fetchval("SELECT 1")
            doc["db_ok"] = True
        except Exception:
            doc["db_ok"] = False
        try:
            r = await get_redis()
            await r.ping()
            doc["redis_ok"] = True
            await r.set("aegis:engine:liveness", _json.dumps(doc))
            await r.set("aegis:engine:heartbeat", doc["ts"])
        except Exception as exc:
            doc["redis_ok"] = False
            log.warning("heartbeat_publish_failed", error=str(exc))
        await asyncio.sleep(15)


async def bootstrap():
    configure_logging()
    cfg = get_config()
    settings = get_settings()

    await init_pool()
    await get_redis()

    alerter = Alerter(settings)
    adapter = KiteAdapter(settings, alerter)
    md_service: MarketDataService | None = None
    orchestrator = None

    if settings.kite_api_key and settings.kite_user_id and settings.kite_totp_secret:
        try:
            adapter.ensure_token()
            log.info("kite_auth_ok")
        except Exception as exc:
            log.error("kite_auth_failed", error=str(exc))
        # Capital is read from margins; if no trading segment is active yet this is
        # unavailable — warn (not fatal). Becomes mandatory in Phase 2.
        try:
            margins = adapter.margins("equity")
            net = margins.get("net") if isinstance(margins, dict) else None
            log.info("kite_margins_ok", equity_net=net)
        except Exception as exc:
            log.warning("kite_margins_unavailable", error=str(exc))

        # Run market data in the background so boot isn't blocked by the first
        # (potentially long) backfill; later boots resume incrementally.
        md_service = MarketDataService(adapter=adapter, config=cfg, settings=settings, alerter=alerter)
        # Phase 2-5 trading stack: cold-start recovery, fast-loop guard wiring, and
        # the gated slow-loop decision chain (idle until funded + operator-enabled).
        try:
            executor, risk_engine, orchestrator = _build_trading_stack(cfg, settings, adapter, md_service, alerter)
            await adopt_open_positions(executor)
            md_service.on_ltp = _make_ltp_handler(executor)

            # Phase 4: opt-in meta-label filter (off unless enabled AND a model is active).
            if (getattr(cfg.system, "meta_label", {}) or {}).get("enabled"):
                try:
                    from research.registry import load_labeler
                    orchestrator.meta_labeler = await load_labeler()
                    log.info("meta_labeler", active=orchestrator.meta_labeler is not None)
                except Exception as exc:
                    log.warning("meta_labeler_load_failed", error=str(exc))

            async def _failsafe(reason: str) -> None:
                """Square off everything + halt — wired to prolonged feed staleness."""
                try:
                    for g in list(executor.structures.all()):
                        await close_structure(executor, g, "failsafe", force=True)
                    await safe_exit_all(executor, reason)
                except Exception as exc:
                    log.error("failsafe_handler_error", error=str(exc))
            md_service.on_failsafe = _failsafe
            asyncio.create_task(_manage_loop(cfg, risk_engine, executor, md_service))  # always-on risk mgmt
            asyncio.create_task(_slow_loop(cfg, orchestrator, risk_engine, md_service))
            try:
                _rec = await recover_stuck_commands()   # P1#12: replay crashed-mid-flight commands
                if _rec:
                    log.info("commands_recovered", count=_rec)
            except Exception as exc:
                log.warning("command_recovery_failed", error=str(exc))
            asyncio.create_task(_command_loop(executor))  # durable operator commands from the API
            log.info("trading_stack_ready", mode=cfg.execution.mode)
        except Exception as exc:
            log.error("trading_stack_init_failed", error=str(exc))
        asyncio.create_task(_safe_start(md_service))
    else:
        log.warning("kite_credentials_missing_skipping_market_data")

    scheduler = build_scheduler()
    # NOTE: CronTrigger does NOT inherit the scheduler tz — pass it explicitly.
    hh, mm = cfg.system.token_refresh_time.split(":")
    scheduler.add_job(
        _daily_token_refresh,
        CronTrigger(hour=int(hh), minute=int(mm), timezone=str(IST)),
        args=[adapter, md_service],
        id="token_refresh", replace_existing=True,
    )
    if md_service is not None:
        scheduler.add_job(
            md_service.refresh_instruments_job,
            CronTrigger(hour=8, minute=15, timezone=str(IST)),
            id="instruments_refresh", replace_existing=True,
        )
        scheduler.add_job(
            md_service.nightly_backfill_job,
            CronTrigger(hour=16, minute=0, timezone=str(IST)),
            id="nightly_backfill", replace_existing=True,
        )
        # Per-instrument ATM IV snapshot just after close (Phase 2.2) -> IV Rank history.
        scheduler.add_job(
            md_service.snapshot_iv_job,
            CronTrigger(hour=15, minute=45, timezone=str(IST)),
            id="iv_snapshot", replace_existing=True,
        )
    # Paper auto-run: arm the orchestrator over the market window when in paper mode
    # (paper_capital > 0). Gated so it never auto-arms live trading.
    if float(getattr(cfg.risk, "paper_capital", 0) or 0) > 0:
        scheduler.add_job(_paper_autorun_enable, CronTrigger(hour=9, minute=15, timezone=str(IST)),
                          id="paper_autorun_enable", replace_existing=True)
        scheduler.add_job(_paper_autorun_disable, CronTrigger(hour=15, minute=30, timezone=str(IST)),
                          id="paper_autorun_disable", replace_existing=True)
        log.info("paper_autorun_scheduled", enable="09:15", disable="15:30")
    scheduler.add_job(_eod_summary, CronTrigger(hour=15, minute=35, timezone=str(IST)),
                      args=[alerter], id="eod_summary", replace_existing=True)
    # Data platform (Pillar 1): compound the curated F&O history forward each
    # evening into the lake + shared TimescaleDB. Best-effort; off unless enabled.
    dp_cfg = getattr(cfg.system, "dataplatform", {}) or {}
    if dp_cfg.get("enabled"):
        dh, dmn = str(dp_cfg.get("ingest_time", "18:45")).split(":")
        scheduler.add_job(_dataplatform_ingest_job, CronTrigger(hour=int(dh), minute=int(dmn), timezone=str(IST)),
                          args=[cfg], id="dataplatform_ingest", replace_existing=True)
        log.info("dataplatform_ingest_scheduled", at=f"{dh}:{dmn}")
    # Nightly meta-labeler retrain (Tier 2 ML): trains on the audit trail, activates
    # only after passing OOS validation, then hot-reloads into the orchestrator.
    meta_cfg = getattr(cfg.system, "meta_label", {}) or {}
    if orchestrator is not None and meta_cfg.get("enabled"):
        mh, mm = str(meta_cfg.get("retrain_time", "16:30")).split(":")
        scheduler.add_job(_meta_retrain_job, CronTrigger(hour=int(mh), minute=int(mm), timezone=str(IST)),
                          args=[cfg, orchestrator], id="meta_retrain", replace_existing=True)
        log.info("meta_retrain_scheduled", at=f"{mh}:{mm}")
    # Friday-evening edge-decay report (Tier-3): weekly expectancy trend per sleeve.
    scheduler.add_job(_edge_report_job, CronTrigger(day_of_week="fri", hour=16, minute=45, timezone=str(IST)),
                      args=[alerter], id="edge_report", replace_existing=True)
    # Daily black-box journal at 17:00 IST (after the ML retrain) — trades, anomalies,
    # funnel, learning status -> daily_journal table + email. Review fuel.
    scheduler.add_job(_journal_job, CronTrigger(hour=17, minute=0, timezone=str(IST)),
                      args=[alerter], id="daily_journal", replace_existing=True)
    # Daily health digest — a morning snapshot email of the live system.
    hd = getattr(cfg.system, "health_digest", {}) or {}
    if hd.get("enabled", True):
        hh, mm = str(hd.get("time", "08:30")).split(":")
        scheduler.add_job(_health_digest_job, CronTrigger(hour=int(hh), minute=int(mm), timezone=str(IST)),
                          args=[alerter], id="health_digest", replace_existing=True)
        log.info("health_digest_scheduled", at=f"{hh}:{mm}")
    scheduler.start()
    asyncio.create_task(_heartbeat_loop(adapter))   # P1#13: independent liveness beacon
    log.info("engine_started", mode=cfg.execution.mode)
    return adapter, scheduler, md_service


async def main() -> None:
    adapter, scheduler, md_service = await bootstrap()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # signal handlers unavailable (e.g. on Windows)
    try:
        await stop.wait()
    finally:
        scheduler.shutdown(wait=False)
        if md_service is not None:
            await md_service.stop()
        await close_pool()
        await close_redis()
        log.info("engine_stopped")


if __name__ == "__main__":
    asyncio.run(main())
