"""Multi-leg defined-risk structure execution for F&O (Phase 5 F&O enablement).

Each leg is sim-filled at its live option quote and stored as a real position row
(linked by correlation_id). A StructureGuard tracks COMBINED P&L across the legs
and exits the whole structure together: book at a fraction of max profit, stop at
the defined max loss, else hold (marked-to-market). Defined-risk only — every short
leg has a long hedge (the pipeline guarantees this).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from common.db import execute, fetch
from common.logging import get_logger
from common.market_time import today_ist
from data.option_chain import resolve_option
from execution.models import Decision

log = get_logger("structures")


def _structure_width(structure: dict) -> float:
    """Strike width of the defined-risk structure (per unit). Iron condor sides are
    built symmetrically, so one side's width is THE width."""
    if structure.get("type") == "iron_condor":
        return abs(float(structure["short_legs"][0]) - float(structure["long_legs"][0]))
    return abs(float(structure["short_leg"]) - float(structure["long_leg"]))


def fill_based_risk(structure: dict, legs: list["_Leg"]) -> tuple[float, float, float]:
    """(net_premium, max_loss, max_profit) in rupees from the ACTUAL fills — not the
    model that proposed the structure. net > 0 = credit received, net < 0 = debit paid.
    Credit: max loss = width*qty - credit, max profit = credit.
    Debit:  max loss = debit,              max profit = width*qty - debit."""
    net = sum((leg.entry * leg.qty if leg.side == "SELL" else -leg.entry * leg.qty) for leg in legs)
    width_rupees = _structure_width(structure) * (legs[0].qty if legs else 0)
    if net >= 0:
        return net, max(0.01, width_rupees - net), max(0.01, net)
    debit = -net
    return net, max(0.01, debit), max(0.01, width_rupees - debit)


@dataclass
class _Leg:
    position_id: int
    token: int
    tradingsymbol: str
    side: str          # BUY / SELL
    qty: int
    entry: float
    fees: float


@dataclass
class StructureGuard:
    correlation_id: str
    name: str
    stype: str
    legs: list[_Leg]
    max_loss_total: float
    max_profit_total: float
    entry_fees: float = 0.0
    target_fraction: float = 0.5    # book profit at 50% of fill-based max profit
    stop_fraction: float = 0.5      # cut at 50% of fill-based max loss (config: fno.exits)
                                    # — never ride to the full defined loss; that stays
                                    # the gap floor, not the plan
    expiry: date | None = None      # option expiry — drives the min-DTE time exit
    opened_on: date | None = None   # entry date — drives the max-holding time exit
    exit_retries: int = 0           # cycles an exit was postponed waiting for a sane book

    def tokens(self) -> list[int]:
        return [leg.token for leg in self.legs]

    def combined_pnl(self, prices: dict) -> float | None:
        pnl = 0.0
        for leg in self.legs:
            cur = prices.get(leg.token)
            if cur is None:
                return None  # need every leg priced
            pnl += (cur - leg.entry) * leg.qty if leg.side == "BUY" else (leg.entry - cur) * leg.qty
        return pnl - self.entry_fees

    def decide(self, prices: dict) -> tuple[str | None, float | None]:
        pnl = self.combined_pnl(prices)
        if pnl is None:
            return None, None
        if pnl >= self.target_fraction * self.max_profit_total:
            return "TARGET", pnl
        if pnl <= -self.stop_fraction * self.max_loss_total:
            return "STOP", pnl
        return "HOLD", pnl


def _legs_from_structure(structure: dict) -> list[tuple[str, float, str]]:
    """[(opt, strike, side)] — BUY the long_leg(s), SELL the short_leg(s)."""
    if structure["type"] == "iron_condor":
        sc, sp = structure["short_legs"]
        lc, lp = structure["long_legs"]
        return [("CE", sc, "SELL"), ("CE", lc, "BUY"), ("PE", sp, "SELL"), ("PE", lp, "BUY")]
    opt = structure["opt"]
    return [(opt, structure["long_leg"], "BUY"), (opt, structure["short_leg"], "SELL")]


class StructureManager:
    def __init__(self) -> None:
        self.by_corr: dict[str, StructureGuard] = {}
        self._by_token: dict[int, set[str]] = {}

    def register(self, guard: StructureGuard) -> None:
        self.by_corr[guard.correlation_id] = guard
        for t in guard.tokens():
            self._by_token.setdefault(t, set()).add(guard.correlation_id)

    def unregister(self, correlation_id: str) -> None:
        guard = self.by_corr.pop(correlation_id, None)
        if guard:
            for t in guard.tokens():
                ids = self._by_token.get(t)
                if ids:
                    ids.discard(correlation_id)

    def for_token(self, token: int) -> list[StructureGuard]:
        return [self.by_corr[c] for c in self._by_token.get(token, set()) if c in self.by_corr]

    def all(self) -> list[StructureGuard]:
        return list(self.by_corr.values())


async def open_structure(executor, name: str, expiry, structure: dict, lots: int, lot_size: int,
                         strike_step: float, correlation_id: str, signal_id: int | None) -> dict:
    qty_per = lots * lot_size
    legs: list[_Leg] = []
    total_fees = 0.0
    for opt, strike, side in _legs_from_structure(structure):
        oi = await resolve_option(name, expiry, strike, opt)
        if oi is None:
            for leg in legs:
                await executor.close(leg.position_id, "structure_leg_unresolved")
            return {"outcome": "REJECTED", "reason": f"leg {opt}{strike} unresolved", "correlation_id": correlation_id}
        inst = {"instrument_token": oi["instrument_token"], "tradingsymbol": oi["tradingsymbol"],
                "exchange": "NFO", "lot_size": lot_size, "instrument_type": opt}
        dec = Decision(correlation_id=correlation_id, sleeve="fno", instrument=inst, side=side,
                       quantity=qty_per, order_type="MARKET", product="NRML", signal_id=signal_id)
        fill = await executor.sim.simulate(dec)
        if fill is None:
            for leg in legs:
                await executor.close(leg.position_id, "structure_leg_no_quote")
            return {"outcome": "REJECTED", "reason": f"no quote for {oi['tradingsymbol']}", "correlation_id": correlation_id}
        pid = await executor.book.open_position(dec, fill, "simulated_fill")
        total_fees += fill.fees["total"]
        legs.append(_Leg(pid, oi["instrument_token"], oi["tradingsymbol"], side, qty_per, fill.price, fill.fees["total"]))

    # Risk from the ACTUAL fills, not the model that proposed the structure. The
    # sizing approved a modeled max loss; if the market filled us into materially
    # more risk than approved, unwind immediately rather than hold an unsized bet.
    exits = (getattr(executor.config.strategy, "fno", {}) or {}).get("exits", {}) or {}
    net, max_loss_total, max_profit_total = fill_based_risk(structure, legs)
    modeled_loss = float(structure["max_loss_per_lot"]) * lots
    overrun = float(exits.get("max_fill_risk_overrun", 1.25) or 1.25)
    if modeled_loss > 0 and max_loss_total > modeled_loss * overrun:
        log.error("structure_fill_risk_overrun", name=name, modeled=round(modeled_loss, 2),
                  actual=round(max_loss_total, 2), overrun=overrun)
        for leg in legs:
            await executor.close(leg.position_id, "fill_risk_overrun")
        return {"outcome": "REJECTED", "correlation_id": correlation_id,
                "reason": f"fill risk Rs {max_loss_total:,.0f} exceeds sized Rs {modeled_loss:,.0f} x{overrun}"}

    # Persist the structure's real risk onto its legs (max_loss / n_legs each) so the
    # portfolio open-R ceiling and the per-sleeve expectancy guard finally SEE F&O:
    # the legs sum to the structure's max loss, and the mean leg R-multiple equals
    # the structure's R-multiple. The structure_meta blob makes the guard fully
    # reconstructable on cold start — an engine restart must never orphan open risk.
    guard = StructureGuard(
        correlation_id, name, structure["type"], legs, max_loss_total, max_profit_total,
        entry_fees=total_fees,
        target_fraction=float(exits.get("target_fraction", 0.5) or 0.5),
        stop_fraction=float(exits.get("stop_fraction", 0.5) or 0.5),
        expiry=expiry, opened_on=today_ist())
    r_per_leg = round(max_loss_total / max(1, len(legs)), 2)
    meta = {"structure_meta": {
        "name": name, "stype": structure["type"], "max_loss_total": round(max_loss_total, 2),
        "max_profit_total": round(max_profit_total, 2), "entry_fees_total": round(total_fees, 2),
        "target_fraction": guard.target_fraction, "stop_fraction": guard.stop_fraction,
        "expiry": str(expiry) if expiry else None, "opened_on": str(guard.opened_on)}}
    await execute(
        "UPDATE positions SET r_rupees=$2, raw = COALESCE(raw,'{}'::jsonb) || $3::jsonb "
        "WHERE id = ANY($1::bigint[])",
        [leg.position_id for leg in legs], r_per_leg, json.dumps(meta))
    executor.structures.register(guard)
    log.info("structure_opened", name=name, type=structure["type"], lots=lots,
             net_premium=round(net, 2), max_loss=round(max_loss_total, 2),
             max_profit=round(max_profit_total, 2), modeled_max_loss=round(modeled_loss, 2),
             target_fraction=guard.target_fraction, stop_fraction=guard.stop_fraction,
             legs=[(leg.tradingsymbol, leg.side, leg.entry) for leg in legs])
    return {"outcome": "FILLED", "correlation_id": correlation_id, "legs": len(legs),
            "net_premium": round(net, 2), "max_loss": round(max_loss_total, 2),
            "max_profit": round(max_profit_total, 2), "position_ids": [leg.position_id for leg in legs]}


async def close_structure(executor, guard: StructureGuard, reason: str,
                          prices: dict | None = None, force: bool = False) -> float | None:
    """Close every leg — but NEVER through a broken book. Before crossing, each leg's
    top-of-book is sanity-checked (two-sided, spread <= max_book_spread_pct) and the
    implied total loss is capped at max_close_loss_overrun x the DEFINED max loss
    (a vertical can never rationally cost more than its width to close — Jun-12 tape:
    one leg's rogue ask turned a -10k stop into a -37k fill). On a bad book the exit
    is POSTPONED (returns None; caller retries next cycle) up to max_exit_retries,
    then forced at the marks. `force=True` (kill-switch / failsafe / operator) skips
    the postpone path — those exits must happen now."""
    exits = (getattr(executor.config.strategy, "fno", {}) or {}).get("exits", {}) or {}
    max_spread = float(exits.get("max_book_spread_pct", 8) or 0)
    cap_mult = float(exits.get("max_close_loss_overrun", 1.15) or 1.15)
    max_retries = int(exits.get("max_exit_retries", 5) or 0)

    exit_px: dict = dict(prices or {})
    if not force and max_spread > 0:
        sane = True
        try:
            keys = [f"NFO:{leg.tradingsymbol}" for leg in guard.legs]
            q = await executor.governor.call("quote", executor.adapter.quote, keys)
            slip = executor.sim.slippage_bps / 10000.0
            px_map: dict = {}
            implied = 0.0
            for leg in guard.legs:
                d = (q.get(f"NFO:{leg.tradingsymbol}") or {}).get("depth") or {}
                bid = float((d.get("buy") or [{}])[0].get("price") or 0)
                ask = float((d.get("sell") or [{}])[0].get("price") or 0)
                mid = (bid + ask) / 2.0
                if bid <= 0 or ask < bid or mid <= 0 or (ask - bid) / mid * 100.0 > max_spread:
                    sane = False
                    break
                # exit crosses: short legs buy back at the ask, long legs sell at the bid
                px = ask * (1 + slip) if leg.side == "SELL" else bid * (1 - slip)
                px_map[leg.token] = round(px, 2)
                implied += (px - leg.entry) * leg.qty if leg.side == "BUY" else (leg.entry - px) * leg.qty
            if sane and guard.max_loss_total > 0 and implied < -(guard.max_loss_total * cap_mult):
                sane = False   # books pass individually but the combined cost is absurd
            if sane:
                exit_px = px_map
        except Exception as exc:
            log.warning("structure_exit_book_check_failed", name=guard.name, error=str(exc))
            sane = False
        if not sane:
            guard.exit_retries += 1
            if guard.exit_retries <= max_retries:
                log.warning("structure_exit_postponed_bad_book", name=guard.name,
                            reason=reason, retry=guard.exit_retries)
                return None   # caller retries next cycle — never cross a broken book
            log.error("structure_exit_forced_after_retries", name=guard.name, reason=reason)
            if executor.alerter:
                await executor.alerter.send_async(
                    "Structure exit forced on bad book",
                    f"{guard.name} {guard.stype}: book stayed untradeable for "
                    f"{guard.exit_retries} cycles — closing at marks. Check fills.")

    realized = 0.0
    for leg in guard.legs:
        # Cross at the validated top-of-book price; the mark is only the fallback.
        r = await executor.close(leg.position_id, reason,
                                 price=exit_px.get(leg.token),
                                 fallback_price=(prices or {}).get(leg.token))
        realized += r or 0.0
    executor.structures.unregister(guard.correlation_id)
    # Re-entry cooldown on the underlying so we don't reopen the same structure next
    # cycle (today's churn: 28/32 structures reopened within 3 minutes).
    try:
        cd = float(getattr(executor.config.risk, "reentry_cooldown_minutes", 0) or 0)
        if cd:
            from common.cooldown import set_cooldown
            await set_cooldown(f"fno:{guard.name}", cd)
    except Exception:
        pass
    log.info("structure_closed", name=guard.name, type=guard.stype, reason=reason, realized=round(realized, 2))
    return realized


async def rebuild_structures(executor) -> set[int]:
    """Cold-start recovery for multi-leg structures: regroup open F&O legs by
    correlation_id using the persisted structure_meta and re-register their guards.
    Returns the position ids covered (so per-leg recovery skips them). Without this,
    an engine restart leaves open structures with NO stop/target management."""
    rows = await fetch(
        "SELECT id, correlation_id, instrument_token, tradingsymbol, side, quantity, "
        "average_price, raw FROM positions WHERE status='open' AND sleeve='fno'")
    by_corr: dict[str, list[dict]] = {}
    for r in rows:
        by_corr.setdefault(str(r["correlation_id"]), []).append(dict(r))

    covered: set[int] = set()
    for corr, legs_rows in by_corr.items():
        meta = None
        legs: list[_Leg] = []
        for r in legs_rows:
            raw = r["raw"] or {}
            if isinstance(raw, str):
                raw = json.loads(raw)
            meta = meta or raw.get("structure_meta")
            fees = float((raw.get("entry_fees") or {}).get("total", 0))
            legs.append(_Leg(r["id"], int(r["instrument_token"]), r["tradingsymbol"],
                             r["side"], int(r["quantity"]), float(r["average_price"]), fees))
        if not meta:
            log.warning("structure_rebuild_no_meta", correlation_id=corr,
                        legs=[r["tradingsymbol"] for r in legs_rows])
            continue
        guard = StructureGuard(
            corr, meta.get("name", ""), meta.get("stype", ""), legs,
            float(meta.get("max_loss_total") or 0), float(meta.get("max_profit_total") or 0),
            entry_fees=float(meta.get("entry_fees_total") or 0),
            target_fraction=float(meta.get("target_fraction", 0.5) or 0.5),
            stop_fraction=float(meta.get("stop_fraction", 0.5) or 0.5),
            expiry=date.fromisoformat(meta["expiry"]) if meta.get("expiry") else None,
            opened_on=date.fromisoformat(meta["opened_on"]) if meta.get("opened_on") else None)
        executor.structures.register(guard)
        covered.update(leg.position_id for leg in legs)
        log.info("structure_rebuilt", name=guard.name, type=guard.stype, legs=len(legs),
                 max_loss=guard.max_loss_total, expiry=str(guard.expiry))
    return covered


def _mid_prices(guard: StructureGuard, q: dict, max_spread_pct: float = 8.0) -> dict | None:
    """Per-leg MID (top bid/ask) marks. `last_price` is poison for spread marking —
    one stale leg against one fresh leg fabricates combined P&L (Jun-12 morning: the
    23300PE marked BELOW the 23250PE seconds after open, firing a fake stop). A live
    two-sided book with a sane spread is required for EVERY leg: a 90/228 book passes
    a naive bid<ask check but its 'mid' is fiction (Jun-12 close: that fiction
    triggered a stop and the fill paid 3x fair). None => skip the cycle."""
    prices: dict = {}
    for leg in guard.legs:
        d = (q.get(f"NFO:{leg.tradingsymbol}") or {}).get("depth") or {}
        try:
            bid = float((d.get("buy") or [{}])[0].get("price") or 0)
            ask = float((d.get("sell") or [{}])[0].get("price") or 0)
        except (TypeError, ValueError, IndexError):
            return None
        mid = (bid + ask) / 2.0
        if bid <= 0 or ask <= 0 or ask < bid or mid <= 0:
            return None
        if max_spread_pct > 0 and (ask - bid) / mid * 100.0 > max_spread_pct:
            return None
        prices[leg.token] = round(mid, 2)
    return prices


async def mark_structures(executor, adapter, governor) -> list[dict]:
    """Poll-based MTM (slow-loop cadence): time exits first (min DTE / max holding),
    then quote each open structure's legs and book/stop on combined P&L computed on
    MID prices (never last-trade). No decisions during the opening auction-noise
    window (`exits.no_mark_before`) — opening prints are not marks."""
    out = []
    exits = (getattr(executor.config.strategy, "fno", {}) or {}).get("exits", {}) or {}
    today = today_ist()
    # Opening window: books are crossed/one-sided and prints are disordered. Neither
    # price stops nor time exits are urgent enough to act on garbage.
    no_mark_before = str(exits.get("no_mark_before", "09:25") or "")
    if no_mark_before:
        from common.market_time import now_ist, parse_hhmm
        if now_ist().timetz().replace(tzinfo=None) < parse_hhmm(no_mark_before):
            return out
    for guard in executor.structures.all():
        # Time exits differ by structure class: CREDIT is managed at ~21 DTE (research:
        # beats hold-to-expiry risk-adjusted — gamma outgrows theta from there); DEBIT
        # gets a short pre-expiry window plus a theta-bleed holding cap.
        is_credit = "credit" in (guard.stype or "") or guard.stype == "iron_condor"
        if is_credit:
            min_dte = int(exits.get("credit_min_exit_dte", 21) or 0)
            max_held = int(exits.get("credit_max_holding_days", 0) or 0)
        else:
            min_dte = int(exits.get("min_exit_dte", 2) or 0)
            max_held = int(exits.get("max_holding_days", 10) or 0)
        if guard.expiry and min_dte and (guard.expiry - today).days <= min_dte:
            realized = await close_structure(executor, guard, "structure_time_dte")
            if realized is not None:
                out.append({"name": guard.name, "type": guard.stype, "action": "STOP",
                            "reason": "time_dte", "realized": round(realized, 2)})
            continue
        if guard.opened_on and max_held and (today - guard.opened_on).days >= max_held:
            realized = await close_structure(executor, guard, "structure_time_held")
            if realized is not None:
                out.append({"name": guard.name, "type": guard.stype, "action": "STOP",
                            "reason": "time_held", "realized": round(realized, 2)})
            continue
        keys = [f"NFO:{leg.tradingsymbol}" for leg in guard.legs]
        try:
            q = await governor.call("quote", adapter.quote, keys)
        except Exception as exc:
            log.warning("structure_mark_quote_failed", error=str(exc))
            continue
        prices = _mid_prices(guard, q, float(exits.get("max_book_spread_pct", 8) or 0))
        if prices is None:
            log.info("structure_mark_skipped_no_live_book", name=guard.name)
            continue
        action, pnl = guard.decide(prices)
        if action in ("STOP", "TARGET"):
            realized = await close_structure(executor, guard, f"structure_{action.lower()}", prices)
            if realized is None:
                continue   # postponed: bad book — guard stays armed, retry next cycle
            out.append({"name": guard.name, "type": guard.stype, "action": action, "realized": round(realized, 2)})
        elif action == "HOLD":
            # Persist per-leg MTM: option legs aren't on the tick feed, so this is the
            # ONLY writer of their unrealized P&L — without it the kill switch and
            # drawdown circuit are blind to open-structure losses intraday.
            for leg in guard.legs:
                if leg.token in prices:
                    try:
                        await executor.book.update_unrealized(leg.position_id, prices[leg.token])
                    except Exception as exc:
                        log.warning("structure_mtm_persist_failed", id=leg.position_id, error=str(exc))
            out.append({"name": guard.name, "type": guard.stype, "action": "HOLD", "unrealized": round(pnl, 2)})
    return out
