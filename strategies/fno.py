"""F&O pipeline (spec §5.2). Funnel: eligibility(ban) -> IV-regime routing
(decisive) -> DTE -> direction/OI -> defined-risk structure build -> Greeks ->
risk. HARD RULE: no naked option selling — every short leg is paired with a long
hedge so max loss is finite and R-sizable. Structure premiums are Black-Scholes
model values (real spot + IV); the live orchestrator can swap in chain quotes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from common.market_time import today_ist
from data.options import bs_price, greeks, year_fraction
from strategies.base import GateRunner, PipelineResult, Signal


@dataclass
class FnoContext:
    spot: float
    iv: float                  # decimal, e.g. 0.18
    iv_rank: float             # 0..100
    dte: int                   # days to expiry
    direction: str             # bullish | bearish | neutral (from price + OI)
    lot_size: int
    expiry: date
    is_banned: bool = False
    strike_step: float = 50.0
    oi_signal: str = ""
    risk_free: float = 0.065
    iv_chg_5d: float = 0.0       # ATM IV % change over ~5 sessions (vol-direction guard)
    is_expiry_day: bool = False  # TODAY is an expiry date for this underlying (any series)
    extra: dict = field(default_factory=dict)


def _px(spot, K, iv, dte, r, opt):
    return bs_price(spot, K, max(dte, 0) / 365.0, r, iv, opt)


def _short_strike_for_delta(spot, iv, dte, r, opt, step, hi=0.22):
    """Walk OTM from ATM to the first strike whose |delta| <= hi — a proper
    credit-spread short leg (config delta.credit_short_leg), not a near-ATM strike."""
    t = max(dte, 0) / 365.0
    atm = round(spot / step) * step
    direction = step if opt == "CE" else -step
    last = atm + direction
    for i in range(1, 40):
        k = atm + direction * i
        if k <= 0:
            break
        last = k
        if abs(greeks(spot, k, t, r, iv, opt)["delta"]) <= hi:
            return k
    return last


def build_structure(regime_class: str, ctx: FnoContext, short_delta_max: float = 0.22,
                    width_steps: int = 2, condor_delta_max: float = 0.20) -> dict | None:
    """Map (IV regime, direction) -> a DEFINED-RISK structure with finite max loss.

    SHORT-PREMIUM FIRST (the VRP research side: implied vol is systematically rich vs
    realized — sellers harvest, buyers pay): medium AND high IV route to credit
    structures — directional bias -> credit spread in that direction, neutral -> iron
    condor. Debit spreads only in genuinely LOW IV with a directional view (cheap vol
    + trend is the one regime where owning premium makes sense).

    `width_steps` sets the wing width in strike steps: 1-step (50pt NIFTY) wings get
    15-20% of their credit eaten by fees; ~2 steps is the cost-efficiency sweet spot."""
    spot, step, iv, dte, r, lot = ctx.spot, ctx.strike_step, ctx.iv, ctx.dte, ctx.risk_free, ctx.lot_size
    atm = round(spot / step) * step
    d = ctx.direction
    width = step * max(1, int(width_steps))

    def debit_spread(opt, k1, k2):
        net = _px(spot, k1, iv, dte, r, opt) - _px(spot, k2, iv, dte, r, opt)
        return max(0.01, net) * lot, net

    def credit_of(opt, ks, kb):
        return _px(spot, ks, iv, dte, r, opt) - _px(spot, kb, iv, dte, r, opt)

    if regime_class == "buy_debit":               # LOW IV only -> own premium with the trend
        if d == "bullish":
            ml, net = debit_spread("CE", atm, atm + width)
            return {"type": "bull_call_debit", "short_leg": atm + width, "long_leg": atm,
                    "opt": "CE", "max_loss_per_lot": round(ml, 2), "net_debit": round(net, 2)}
        if d == "bearish":
            ml, net = debit_spread("PE", atm, atm - width)
            return {"type": "bear_put_debit", "short_leg": atm - width, "long_leg": atm,
                    "opt": "PE", "max_loss_per_lot": round(ml, 2), "net_debit": round(net, 2)}
        return None

    # medium ("spread") and high ("sell_credit") IV -> SHORT premium, defined risk.
    if d == "bullish":                             # bull put credit
        ks = _short_strike_for_delta(spot, iv, dte, r, "PE", step, hi=short_delta_max)
        kb = ks - width
        cr = credit_of("PE", ks, kb)
        return {"type": "bull_put_credit", "short_leg": ks, "long_leg": kb, "opt": "PE",
                "max_loss_per_lot": round(max(0.01, width - cr) * lot, 2), "net_credit": round(cr, 2)}
    if d == "bearish":                             # bear call credit
        ks = _short_strike_for_delta(spot, iv, dte, r, "CE", step, hi=short_delta_max)
        kb = ks + width
        cr = credit_of("CE", ks, kb)
        return {"type": "bear_call_credit", "short_leg": ks, "long_leg": kb, "opt": "CE",
                "max_loss_per_lot": round(max(0.01, width - cr) * lot, 2), "net_credit": round(cr, 2)}
    # neutral -> iron condor (both credit spreads; shorts at the condor delta band)
    ksc = _short_strike_for_delta(spot, iv, dte, r, "CE", step, hi=condor_delta_max)
    ksp = _short_strike_for_delta(spot, iv, dte, r, "PE", step, hi=condor_delta_max)
    cr_c = credit_of("CE", ksc, ksc + width)
    cr_p = credit_of("PE", ksp, ksp - width)
    ml = max(0.01, width - (cr_c + cr_p)) * lot
    return {"type": "iron_condor", "short_leg": ksc, "long_leg": ksc + width, "opt": "CE",
            "short_legs": [ksc, ksp], "long_legs": [ksc + width, ksp - width],
            "max_loss_per_lot": round(ml, 2), "net_credit": round(cr_c + cr_p, 2)}


class FnoPipeline:
    sleeve = "fno"

    def __init__(self, config) -> None:
        self.p = config.strategy.fno

    async def evaluate(self, instrument: dict, ctx: FnoContext) -> PipelineResult:
        g = GateRunner()
        p = self.p

        # 1. eligibility (F&O ban)
        if not g.add("eligibility", not ctx.is_banned, 1.0 if not ctx.is_banned else 0.0,
                     banned=ctx.is_banned):
            return g.reject("underlying in F&O ban")

        # 1b. deterministic macro-event gate (RBI/Fed/budget — config-maintained dates).
        # The LLM news veto is per-symbol and fails neutral; scheduled binary events
        # need a hard calendar block, not a sentiment guess.
        ev = p.get("event_calendar", {}) or {}
        ev_dates = set(ev.get("dates") or [])
        if ev_dates:
            today = today_ist()
            horizon = int(ev.get("block_days_before", 1) or 0)
            hit = next((str(today + timedelta(days=k)) for k in range(horizon + 1)
                        if str(today + timedelta(days=k)) in ev_dates), None)
            if not g.add("event_calendar", hit is None, 1.0 if hit is None else 0.0, event_date=hit):
                return g.reject(f"macro event {hit} within {horizon}d — no new structures")

        # 1c. expiry-day gate: the underlying's own expiry day is a pinning regime —
        # the last hours trade on dealer hedging flows, not fundamentals. No new
        # structures (even ones expiring later) on that underlying today.
        if p.get("block_on_expiry_day", True):
            if not g.add("expiry_day", not ctx.is_expiry_day,
                         1.0 if not ctx.is_expiry_day else 0.0, is_expiry_day=ctx.is_expiry_day):
                return g.reject("underlying expiry day — pinning regime, no new structures")

        # 2. IV-regime routing (first, decisive)
        ivr = p.get("iv_rank", {})
        if ctx.iv_rank < ivr.get("low_max", 20):
            regime_class, allowed = "buy_debit", p.get("dte", {}).get("weekly_buy", [3, 10])
        elif ctx.iv_rank > ivr.get("high_min", 70):
            regime_class, allowed = "sell_credit", p.get("dte", {}).get("credit_sell", [15, 45])
        else:
            regime_class, allowed = "spread", p.get("dte", {}).get("swing_buy", [20, 45])
        g.add("iv_regime", True, min(1.0, abs(ctx.iv_rank - 50) / 50 + 0.5),
              iv_rank=ctx.iv_rank, class_=regime_class)

        # 2b. vol-direction guard: a high IV LEVEL invites selling, but IV that is
        # actively SPIKING means the market is repricing risk — selling into that is
        # how short-vol books die. Applies to EVERY premium-selling class (medium and
        # high IV both route to credit structures now).
        if regime_class != "buy_debit":
            spike_max = float(ivr.get("spike_block_chg_pct", 15) or 0)
            spiking = spike_max > 0 and ctx.iv_chg_5d > spike_max
            if not g.add("iv_direction", not spiking, 0.9 if not spiking else 0.0,
                         iv_chg_5d=round(ctx.iv_chg_5d, 1), max_pct=spike_max):
                return g.reject(
                    f"IV +{ctx.iv_chg_5d:.0f}%/5d (> {spike_max:.0f}%) — no credit selling into a vol spike")

        # 3. DTE gate (avoid 0/1 / expiry gambling)
        avoid = p.get("dte", {}).get("avoid", [0, 1])
        dte_ok = ctx.dte > max(avoid) and allowed[0] <= ctx.dte <= allowed[1]
        if not g.add("dte", dte_ok, 1.0 if dte_ok else 0.0, dte=ctx.dte, allowed=allowed):
            return g.reject(f"DTE {ctx.dte} outside {allowed} or in avoid {avoid}")

        # 4. direction / OI — OI buildup that agrees with the price-direction read is a
        # confirmation (higher score). Neutral is tradeable wherever we SELL premium
        # (medium/high IV -> iron condor); only the low-IV debit class needs a trend.
        directional_ok = ctx.direction in ("bullish", "bearish") or regime_class != "buy_debit"
        oi_agrees = ctx.direction != "neutral" and ctx.oi_signal == ctx.direction
        oi_score = 0.9 if oi_agrees else (0.8 if directional_ok else 0.0)
        if not g.add("direction_oi", directional_ok, oi_score,
                     direction=ctx.direction, oi=ctx.oi_signal, oi_confirms=oi_agrees):
            return g.reject("no directional bias (low-IV debit needs a trend)")

        # 4b. credit-universe gate: premium selling only on the configured INDEX
        # underlyings — index options have tight books and no earnings shocks; stock
        # options are reserved for the (rare) low-IV directional debit case.
        if regime_class != "buy_debit":
            allowed = set(p.get("credit_underlyings") or ["NIFTY", "BANKNIFTY"])
            name_ok = (instrument.get("tradingsymbol") or "") in allowed
            if not g.add("credit_universe", name_ok, 1.0 if name_ok else 0.0,
                         allowed=sorted(allowed)):
                return g.reject("premium selling restricted to index underlyings")

        # 5. structure build (NO naked selling — finite max loss); deltas and wing
        # width from config (delta.credit_short_leg / delta.condor_leg / width_steps).
        delta_range = p.get("delta", {})
        sd_max = float((delta_range.get("credit_short_leg") or [0.15, 0.22])[1])
        cd_max = float((delta_range.get("condor_leg") or [0.10, 0.20])[1])
        structure = build_structure(regime_class, ctx, short_delta_max=sd_max,
                                    width_steps=int(p.get("width_steps", 2) or 2),
                                    condor_delta_max=cd_max)
        ml = structure and structure.get("max_loss_per_lot", 0)
        struct_ok = bool(structure) and ml and ml > 0
        if not g.add("structure", struct_ok, 0.9 if struct_ok else 0.0, structure=structure):
            return g.reject("could not build a finite-risk structure")

        # 6. Greeks gate — keyed on the STRUCTURE TYPE (not the IV class): any credit
        # structure validates its short leg; condors use the condor band; debit
        # validates the long leg in the buyer band.
        t = year_fraction(ctx.expiry)
        stype = structure.get("type", "")
        is_credit = "credit" in stype or stype == "iron_condor"
        if is_credit:
            leg = structure.get("short_leg") or (structure.get("short_legs") or [ctx.spot])[0]
            opt = structure.get("opt", "CE")
            dlt = abs(greeks(ctx.spot, leg, t, ctx.risk_free, ctx.iv, opt)["delta"])
            lo, hi = (delta_range.get("condor_leg", [0.10, 0.20]) if stype == "iron_condor"
                      else delta_range.get("credit_short_leg", [0.15, 0.22]))
        else:
            leg = structure.get("long_leg", ctx.spot)
            opt = structure.get("opt", "CE")
            dlt = abs(greeks(ctx.spot, leg, t, ctx.risk_free, ctx.iv, opt)["delta"])
            lo, hi = delta_range.get("buyer", [0.40, 0.60])
        greeks_ok = lo - 0.15 <= dlt <= hi + 0.20  # tolerance band around target
        g.add("greeks", greeks_ok, 1.0 if lo <= dlt <= hi else 0.5, delta=round(dlt, 3), target=[lo, hi])
        if not greeks_ok:
            return g.reject(f"leg delta {dlt:.2f} far from target {[lo, hi]}")

        # 7. risk: max loss finite (sleeve/portfolio ceilings applied by the Risk Engine)
        g.add("risk_finite", True, 0.9, max_loss_per_lot=structure["max_loss_per_lot"])

        side = "BUY" if ctx.direction == "bullish" else ("SELL" if ctx.direction == "bearish" else "NEUTRAL")
        sig = Signal(self.sleeve, instrument, side, structure["type"], round(ctx.spot, 2), 0.0, 0.0,
                     {"structure": structure, "max_loss_per_lot": structure["max_loss_per_lot"],
                      "lot_size": ctx.lot_size, "regime_class": regime_class, "no_naked_selling": True})
        return g.accept(sig)
