"""Swing / positional backtest (daily bars) — the lowest-frequency strategy, and the
one most likely to survive transaction costs (it holds days-to-weeks, so slippage is
amortised over large moves instead of paid on constant turnover). Never validated until
now.

Setup = base breakout above the prior 20-day high, in an uptrend (price > 200-DMA AND
NIFTY > its 200-DMA), ATR stop, 2R target, hard-limit exit. Fundamentals are DISABLED
(technical-only test — we don't archive point-in-time fundamentals, and using today's
would be look-ahead). Equity slippage + the real delivery cost model are applied.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from common.logging import get_logger
from common.market_time import IST
from data import indicators
from data.instruments import get_token, resolve
from data.store import load_candles_range_df
from engine.confidence import ConfidenceModel
from execution.costs import CostModel
from research.features import signal_features
from risk.models import InstrumentKind
from risk.sizing import size_position
from strategies.base import PASS
from strategies.swing import SwingContext, SwingPipeline
from backtest.metrics import compute_metrics
from backtest.sim_broker import BacktestBroker

log = get_logger("swing_backtest")


def _ist_iso(ts) -> str:
    return (ts.tz_convert(IST) if getattr(ts, "tzinfo", None) else ts).isoformat()


async def run_swing_backtest(params, cfg) -> dict:
    conf = ConfidenceModel(cfg)
    cost = CostModel(cfg.execution.cost_model)
    broker = BacktestBroker(cost, float(cfg.execution.slippage_bps))
    pipeline = SwingPipeline(cfg)
    p = cfg.strategy.swing_stocks or {}
    atr_mult = float((p.get("stops") or {}).get("atr_multiple", 2.0))
    max_hold = int((p.get("holding_horizon") or {}).get("hard_limit_days", 60))
    exit_mode = (p.get("exit_mode") or "target").lower()   # "target" (2R) | "trail" (ride trend)
    seg = "equity_delivery"
    warm_from = datetime.combine(params.from_dt - timedelta(days=400), datetime.min.time())
    to_dt = datetime.combine(params.to_dt, datetime.max.time())
    trades: list[dict] = []
    skipped: list[str] = []

    nifty_tok = await get_token("NSE:NIFTY 50")
    nifty = await load_candles_range_df(nifty_tok, "day", warm_from, to_dt) if nifty_tok else pd.DataFrame()
    nifty_up = (nifty["close"] > nifty["close"].rolling(200).mean()) if not nifty.empty else None
    start_ts = pd.Timestamp(params.from_dt, tz=IST)

    for sym in params.symbols:
        inst = await resolve(sym)
        if not inst:
            skipped.append(sym)
            continue
        token = inst["instrument_token"]
        df = await load_candles_range_df(token, "day", warm_from, to_dt)
        if df.empty or len(df) < 220:
            skipped.append(sym)
            continue
        sma200 = df["close"].rolling(200).mean()
        atr = indicators.atr(df, 14)
        prior_high = df["high"].rolling(20).max().shift(1)
        ret20 = df["close"].pct_change(20) * 100.0
        mkt_up = nifty_up.reindex(df.index, method="ffill").fillna(False) if nifty_up is not None else None
        nifty_ret20 = (nifty["close"].pct_change(20) * 100.0).reindex(df.index, method="ffill") if not nifty.empty else None

        open_pos: dict | None = None
        n = len(df)
        for i in range(n):
            ts = df.index[i]
            bar = df.iloc[i]
            if open_pos is not None:
                hi, lo, close = float(bar["high"]), float(bar["low"]), float(bar["close"])
                # Trailing mode: ride the trend — raise the stop under the highest close,
                # no fixed target (let winners run; breakouts pay off in the rare big move).
                if exit_mode == "trail":
                    open_pos["hwm"] = max(open_pos["hwm"], hi)
                    open_pos["stop"] = max(open_pos["stop"], open_pos["hwm"] - open_pos["trail_dist"])
                reason = exitpx = None
                if lo <= open_pos["stop"]:
                    reason, exitpx = "stop", open_pos["stop"]
                elif exit_mode == "target" and hi >= open_pos["target"]:
                    reason, exitpx = "target", open_pos["target"]
                elif (ts - open_pos["entry_ts"]).days >= max_hold:
                    reason, exitpx = "max_hold", close
                if reason:
                    qty, entry = open_pos["qty"], open_pos["entry"]
                    exit_fill = broker.exit_fill("BUY", exitpx)
                    gross = (exit_fill - entry) * qty
                    exit_fees = broker.fees(seg, "SELL", qty, exit_fill)
                    pnl = round(gross - open_pos["entry_fees"] - exit_fees, 2)
                    risk_amt = open_pos["risk_amt"] or 1.0
                    if ts >= start_ts:
                        trades.append({
                            "ts": _ist_iso(ts), "symbol": inst["tradingsymbol"], "sleeve": "swing_stocks",
                            "setup": "base_breakout", "side": "BUY", "entry": entry, "exit": exit_fill,
                            "qty": qty, "pnl": pnl, "r_multiple": round(pnl / risk_amt, 3),
                            "fees": round(open_pos["entry_fees"] + exit_fees, 2), "reason": reason,
                            "features": open_pos.get("features", {})})
                    open_pos = None
            if open_pos is not None or i + 1 >= n or ts < start_ts:
                continue

            lp = float(bar["close"])
            s200 = float(sma200.iloc[i]) if sma200.iloc[i] == sma200.iloc[i] else 0.0
            a = float(atr.iloc[i]) if atr.iloc[i] == atr.iloc[i] else 0.0
            ph = float(prior_high.iloc[i]) if prior_high.iloc[i] == prior_high.iloc[i] else 0.0
            if not s200 or not a or not ph:
                continue
            mkt = bool(mkt_up.iloc[i]) if mkt_up is not None else True
            rs = (float(ret20.iloc[i]) - float(nifty_ret20.iloc[i])) if (nifty_ret20 is not None and ret20.iloc[i] == ret20.iloc[i]) else 0.0
            ctx = SwingContext(last_price=lp, sma200=s200, atr=a, market_uptrend=mkt, sector_strong=True,
                               setup_ok=(lp > ph), setup="base_breakout", event_in_window=False,
                               fundamentals_required=False)
            ctx.rel_strength = rs   # attach for the feature extractor
            res = await pipeline.evaluate(inst, ctx)
            if res.decision != PASS or res.signal is None:
                continue
            confidence = conf.score(res.gates)
            if not conf.passes(confidence):
                continue
            sig = res.signal
            sized = size_position(capital=params.starting_capital, per_trade_risk_pct=params.per_trade_pct,
                                  per_instrument_cap_pct=cfg.risk.per_instrument_cap_pct,
                                  entry_price=sig.entry, stop_price=sig.stop, lot_size=1,
                                  kind=InstrumentKind.EQUITY, confidence=confidence)
            if sized.rejected or sized.quantity <= 0:
                continue
            entry_ref = float(df.iloc[i + 1]["open"])
            fill = broker.entry_fill("BUY", entry_ref)
            qty = sized.quantity
            open_pos = {
                "entry": fill, "qty": qty, "stop": sig.stop, "target": sig.target, "entry_ts": ts,
                "risk_amt": abs(sig.entry - sig.stop) * qty,
                "entry_fees": broker.fees(seg, "BUY", qty, fill),
                "hwm": fill, "trail_dist": atr_mult * a,   # for trailing-stop mode
                "features": signal_features("swing_stocks", ctx, confidence, res.gates, _ist_iso(ts), signal=sig),
            }
        if open_pos is not None:
            last = df.iloc[-1]
            exit_fill = broker.exit_fill("BUY", float(last["close"]))
            qty, entry = open_pos["qty"], open_pos["entry"]
            pnl = round((exit_fill - entry) * qty - open_pos["entry_fees"]
                        - broker.fees(seg, "SELL", qty, exit_fill), 2)
            trades.append({"ts": _ist_iso(df.index[-1]), "symbol": inst["tradingsymbol"], "sleeve": "swing_stocks",
                           "setup": "base_breakout", "side": "BUY", "entry": entry, "exit": exit_fill, "qty": qty,
                           "pnl": pnl, "r_multiple": round(pnl / (open_pos["risk_amt"] or 1.0), 3),
                           "fees": round(open_pos["entry_fees"], 2), "reason": "eod",
                           "features": open_pos.get("features", {})})

    metrics = compute_metrics(trades, params.starting_capital)
    log.info("swing_backtest_complete", names=len(params.symbols), trades=len(trades), net=metrics["net_pnl"])
    return {"metrics": metrics, "trades": trades, "skipped": skipped,
            "params": {"sleeve": "swing_stocks", "symbols": params.symbols, "from": str(params.from_dt),
                       "to": str(params.to_dt), "starting_capital": params.starting_capital,
                       "per_trade_pct": params.per_trade_pct},
            "note": "Technical-only swing (fundamentals disabled). Base-breakout > prior-20d-high in an uptrend."}
