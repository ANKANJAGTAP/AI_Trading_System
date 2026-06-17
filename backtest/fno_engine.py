"""F&O backtest engine (Phase 4 extension).

Replays each underlying's REAL daily price path and runs the live FnoPipeline to build
defined-risk structures, then prices + manages each structure with Black-Scholes (spot
path + theta decay + an IV series from INDIA VIX) until it hits target/stop/expiry.

HONEST MODELLING LIMITS (read before trusting results):
  - Premiums are Black-Scholes MODEL values, not historical option quotes (we don't
    archive historical chains). The strategy itself prices with BS, so this validates
    the structure LOGIC (strike/DTE/direction/exit fractions) over real price paths and
    generates labelled trades — but it will NOT capture IV smile/skew, bid-ask, gap risk
    on short legs, or assignment. Credit-spread results here are likely OPTIMISTIC.
  - IV uses INDIA VIX for indices and as a proxy for stocks; strike steps + expiries are
    synthesised. Treat F&O backtest P&L as directional evidence, not a precise forecast.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from common.logging import get_logger
from common.market_time import IST
from data.instruments import get_token
from data.options import bs_price
from data.options import iv_rank as iv_rank_fn
from data.store import load_candles_range_df
from engine.confidence import ConfidenceModel
from engine.context_builder import daily_direction_from_df
from execution.costs import CostModel
from execution.structures import _legs_from_structure
from research.features import signal_features
from risk.sizing import size_structure
from strategies.base import PASS
from strategies.fno import FnoContext, FnoPipeline
from backtest.metrics import compute_metrics

log = get_logger("fno_backtest")

_KNOWN_STEPS = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "MIDCPNIFTY": 25,
                "SENSEX": 100, "BANKEX": 100}
_R = 0.065


def _strike_step(name: str, spot: float) -> float:
    if name in _KNOWN_STEPS:
        return float(_KNOWN_STEPS[name])
    if spot < 250:   return 5.0
    if spot < 500:   return 10.0
    if spot < 1000:  return 20.0
    if spot < 2500:  return 50.0
    return 100.0


def _choose_dte(iv_rank: float, fno_cfg: dict) -> int:
    th, dte_cfg = fno_cfg.get("iv_rank", {}), fno_cfg.get("dte", {})
    if iv_rank < th.get("low_max", 20):
        w = dte_cfg.get("weekly_buy", [3, 10])
    elif iv_rank > th.get("high_min", 70):
        w = dte_cfg.get("credit_sell", [15, 45])
    else:
        w = dte_cfg.get("swing_buy", [20, 45])
    return int((w[0] + w[1]) // 2)


def structure_pnl(legs: list[tuple], qty: int, spot: float, dte_days: float, iv: float) -> float:
    """Combined rupee P&L of the legs at (spot, dte). legs: [(opt, strike, side, entry_px)]."""
    t = max(0.0, dte_days) / 365.0
    per_unit = 0.0
    for opt, strike, side, entry_px in legs:
        cur = bs_price(spot, strike, t, _R, iv, opt)
        per_unit += (cur - entry_px) if side == "BUY" else (entry_px - cur)
    return per_unit * qty


def slippage_cost(legs: list[tuple], qty: int, spot: float, dte_days: float, iv: float,
                  slip_pct: float) -> float:
    """Realistic option slippage: a haircut of slip_pct on every premium TURNED OVER
    (each leg traded twice — entry + exit). Options carry wide bid-ask, especially OTM
    and low-DTE, so this is the single biggest correction to a BS-model backtest."""
    if slip_pct <= 0:
        return 0.0
    # #23: spread-aware haircut. Instead of one flat slip_pct on every leg, cross each
    # leg by half its (synthetic) bid-ask spread — wider for OTM / short-DTE / high-IV
    # legs — floored at the base slip. Structural stand-in until a real chain is wired.
    from backtest.option_fills import synthetic_spread_pct
    t = max(0.0, dte_days) / 365.0
    base = slip_pct / 100.0
    total = 0.0
    for opt, strike, _side, entry_px in legs:
        leg_prem = entry_px + bs_price(spot, strike, t, _R, iv, opt)
        leg_slip = max(base, synthetic_spread_pct(spot, strike, dte_days, iv) / 2.0)
        total += leg_prem * leg_slip
    return total * qty


async def run_fno_backtest(params, cfg) -> dict:
    conf = ConfidenceModel(cfg)
    cost = CostModel(cfg.execution.cost_model)
    pipeline = FnoPipeline(cfg)
    fno_cfg = cfg.strategy.fno or {}
    max_lots = int(fno_cfg.get("max_lots_per_structure", 0) or 0) or None
    slip_pct = float(fno_cfg.get("slippage_pct", 1.5))   # realistic option slippage
    target_frac, stop_frac = 0.5, 1.0

    fno_uni = {e["name"]: e["underlying"] for e in (cfg.data.universe or {}).get("fno", [])}
    names = params.symbols or list(fno_uni.keys())
    warm_from = datetime.combine(params.from_dt - timedelta(days=400), datetime.min.time())
    to_dt = datetime.combine(params.to_dt, datetime.max.time())
    trades: list[dict] = []
    skipped: list[str] = []

    vix_tok = await get_token("NSE:INDIA VIX")
    vix_df = await load_candles_range_df(vix_tok, "day", warm_from, to_dt) if vix_tok else pd.DataFrame()

    for name in names:
        ukey = fno_uni.get(name)
        tok = await get_token(ukey) if ukey else None
        if not tok:
            skipped.append(name)
            continue
        und = await load_candles_range_df(tok, "day", warm_from, to_dt)
        if und.empty or len(und) < 30:
            skipped.append(name)
            continue
        lot = await _lot_size(name)
        # align VIX to the underlying's dates (forward-fill); fall back to flat 15.
        if not vix_df.empty:
            vix = vix_df["close"].reindex(und.index, method="ffill").bfill()
        else:
            vix = pd.Series(15.0, index=und.index)

        open_s: dict | None = None
        cooldown_until = None
        start_ts = pd.Timestamp(params.from_dt, tz=IST)
        for i in range(len(und)):
            ts = und.index[i]
            bar_date = ts.tz_convert(IST).date() if ts.tzinfo else ts.date()
            spot = float(und["close"].iloc[i])
            vix_now = float(vix.iloc[i]) if vix.iloc[i] == vix.iloc[i] else 15.0
            iv = max(0.01, vix_now / 100.0)
            ivr = iv_rank_fn(vix_now, [float(x) for x in vix.iloc[max(0, i - 250):i + 1].tolist()])

            # ---- manage an open structure against THIS bar ----
            if open_s is not None:
                dte_left = (open_s["expiry"] - bar_date).days
                pnl = structure_pnl(open_s["legs"], open_s["qty"], spot, dte_left, iv)
                reason = None
                if dte_left <= 0:
                    reason = "expiry"
                elif pnl >= target_frac * open_s["max_profit"]:
                    reason = "structure_target"
                elif pnl <= -stop_frac * open_s["max_loss"]:
                    reason = "structure_stop"
                if reason:
                    exit_fees = sum(cost.compute_leg("fno_options", "SELL" if s == "BUY" else "BUY",
                                                     open_s["qty"], max(0.05, bs_price(spot, k,
                                                     max(0.0, dte_left) / 365.0, _R, iv, o)))["total"]
                                    for o, k, s, _e in open_s["legs"])
                    slip = slippage_cost(open_s["legs"], open_s["qty"], spot, dte_left, iv, slip_pct)
                    realized = round(pnl - open_s["entry_fees"] - exit_fees - slip, 2)
                    if ts >= start_ts:
                        trades.append({
                            "ts": (ts.tz_convert(IST) if ts.tzinfo else ts).isoformat(),
                            "symbol": name, "sleeve": "fno", "setup": open_s["type"], "side": "STRUCTURE",
                            "entry": round(open_s["entry_net"], 2), "exit": round(open_s["entry_net"] + pnl / open_s["qty"], 2),
                            "qty": open_s["qty"], "pnl": realized,
                            "r_multiple": round(realized / open_s["max_loss"], 3) if open_s["max_loss"] else 0.0,
                            "fees": round(open_s["entry_fees"] + exit_fees, 2), "reason": reason,
                            "features": open_s.get("features", {})})
                    open_s = None
                    cooldown_until = i + 1   # 1-bar cooldown
            if open_s is not None or ts < start_ts:
                continue
            if cooldown_until is not None and i < cooldown_until:
                continue

            # ---- look for a new structure ----
            dte = _choose_dte(ivr, fno_cfg)
            expiry = bar_date + timedelta(days=dte)
            step = _strike_step(name, spot)
            direction = daily_direction_from_df(und.iloc[: i + 1], spot)
            ctx = FnoContext(spot=spot, iv=round(iv, 4), iv_rank=round(ivr, 1), dte=dte,
                             direction=direction, lot_size=lot, expiry=expiry, is_banned=False,
                             strike_step=step, oi_signal="neutral", risk_free=_R)
            inst = {"tradingsymbol": name, "exchange": "NFO", "instrument_type": "CE", "lot_size": lot}
            res = await pipeline.evaluate(inst, ctx)
            if res.decision != PASS or res.signal is None:
                continue
            confidence = conf.score(res.gates)
            if not conf.passes(confidence):
                continue
            structure = res.signal.detail.get("structure")
            mlpl = (structure or {}).get("max_loss_per_lot", 0)
            if not structure or mlpl <= 0:
                continue
            sized = size_structure(capital=params.starting_capital, per_trade_risk_pct=params.per_trade_pct,
                                   max_loss_per_lot=mlpl, lot_size=lot, confidence=confidence, max_lots=max_lots)
            if sized.rejected or sized.lots < 1:
                continue
            lots, qty = sized.lots, sized.lots * lot
            t0 = max(0.0, dte) / 365.0
            legs = []
            entry_net = 0.0
            entry_fees = 0.0
            for opt, strike, side in _legs_from_structure(structure):
                px = max(0.05, bs_price(spot, strike, t0, _R, iv, opt))
                legs.append((opt, strike, side, px))
                entry_net += (-px if side == "BUY" else px)
                entry_fees += cost.compute_leg("fno_options", side, qty, px)["total"]
            open_s = {
                "legs": legs, "qty": qty, "lots": lots, "type": structure["type"],
                "expiry": expiry, "entry_net": entry_net, "entry_fees": entry_fees,
                "max_loss": mlpl * lots,
                "max_profit": max(0.01, step * lot - mlpl) * lots,
                "features": signal_features("fno", ctx, confidence, res.gates,
                                            ts.tz_convert(IST) if ts.tzinfo else ts, signal=res.signal),
            }

        if open_s is not None:   # square off at the last bar
            spot = float(und["close"].iloc[-1])
            dte_left = max(0, (open_s["expiry"] - (und.index[-1].tz_convert(IST) if und.index[-1].tzinfo else und.index[-1]).date()).days)
            pnl = structure_pnl(open_s["legs"], open_s["qty"], spot, dte_left, iv)
            slip = slippage_cost(open_s["legs"], open_s["qty"], spot, dte_left, iv, slip_pct)
            realized = round(pnl - open_s["entry_fees"] - slip, 2)
            trades.append({"ts": (und.index[-1].tz_convert(IST) if und.index[-1].tzinfo else und.index[-1]).isoformat(),
                           "symbol": name, "sleeve": "fno", "setup": open_s["type"], "side": "STRUCTURE",
                           "entry": round(open_s["entry_net"], 2), "exit": 0.0, "qty": open_s["qty"],
                           "pnl": realized, "r_multiple": round(realized / open_s["max_loss"], 3) if open_s["max_loss"] else 0.0,
                           "fees": round(open_s["entry_fees"], 2), "reason": "eod",
                           "features": open_s.get("features", {})})

    metrics = compute_metrics(trades, params.starting_capital)
    log.info("fno_backtest_complete", names=len(names), trades=len(trades), net=metrics["net_pnl"])
    return {"metrics": metrics, "trades": trades, "skipped": skipped,
            "params": {"sleeve": "fno", "symbols": names, "from": str(params.from_dt),
                       "to": str(params.to_dt), "starting_capital": params.starting_capital,
                       "per_trade_pct": params.per_trade_pct},
            "note": "F&O premiums are Black-Scholes model values (no historical chains) — directional evidence, not precise P&L."}


async def _lot_size(name: str) -> int:
    from common.db import fetchval
    val = await fetchval("SELECT lot_size FROM instruments WHERE name=$1 AND instrument_type IN ('CE','PE') "
                         "AND lot_size>0 ORDER BY expiry DESC NULLS LAST LIMIT 1", name)
    return int(val) if val else 50
