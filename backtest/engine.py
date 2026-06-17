"""Backtest engine (Phase 1 — intraday-equity sleeve).

For each 5m bar it builds the IntradayContext from history up to that bar (via the
SAME pure `intraday_context_from_frames` the live engine uses), runs the real
IntradayPipeline + ConfidenceModel + R-sizing, enters at the NEXT bar's open (no
same-bar look-ahead), and manages stop/target/square-off against subsequent bars'
highs/lows. Costs + slippage reuse the live CostModel.

Swing (daily bars) and F&O (historical option chains) are deliberate extensions —
F&O premiums would be model-on-model without a historical chain, so they're left
for Phase 2 rather than faked here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from common.logging import get_logger
from common.market_time import IST, parse_hhmm
from config.loader import get_config
from data.instruments import resolve
from engine.confidence import ConfidenceModel
from engine.context_builder import intraday_context_from_frames
from execution.costs import CostModel
from risk.models import InstrumentKind
from risk.sizing import size_position
from strategies.base import PASS
from strategies.intraday import IntradayPipeline
from research.discrimination import discriminate
from research.features import signal_features
from backtest.data_window import DataWindow
from backtest.metrics import compute_metrics
from backtest.sim_broker import BacktestBroker
from backtest.execution_model import price_band_breached, resolve_intrabar_exit


def attach_discrimination(result: dict) -> dict:
    """Every backtest auto-reports whether ANY feature separates winners from losers."""
    samples = [{"features": t.get("features", {}), "label": 1 if t.get("pnl", 0) > 0 else 0}
               for t in result.get("trades", []) if t.get("features")]
    if samples:
        result["discrimination"] = discriminate(samples)
    return result

log = get_logger("backtest")


@dataclass
class BacktestParams:
    symbols: list[str]                      # "EXCHANGE:TRADINGSYMBOL"
    from_dt: date
    to_dt: date
    sleeve: str = "intraday_stocks"
    starting_capital: float = 1_000_000.0
    per_trade_pct: float = 1.0
    extra: dict = field(default_factory=dict)


def _ist(ts) -> datetime:
    """pandas Timestamp (tz-aware from the DB) -> IST python datetime."""
    return ts.tz_convert(IST).to_pydatetime()


async def win_load_index(token, from_dt, to_dt):
    from data.store import load_candles_range_df
    return await load_candles_range_df(token, "day",
                                       datetime.combine(from_dt, datetime.min.time()),
                                       datetime.combine(to_dt, datetime.max.time()))


def _close_trade(pos: dict, exit_ref: float, ts, broker: BacktestBroker, seg: str,
                 reason: str, exit_fill_price: float | None = None) -> dict:
    side, qty, entry = pos["side"], pos["qty"], pos["entry"]
    # P25: stop/target pass a pre-computed honest fill (gap-aware); market exits
    # (square-off / eod) leave it None and cross the spread via the cost model.
    exit_fill = exit_fill_price if exit_fill_price is not None else broker.exit_fill(side, exit_ref)
    gross = (exit_fill - entry) * qty if side == "BUY" else (entry - exit_fill) * qty
    exit_side = "SELL" if side == "BUY" else "BUY"
    exit_fees = broker.fees(seg, exit_side, qty, exit_fill)
    pnl = round(gross - pos["entry_fees"] - exit_fees, 2)
    risk_amt = pos["risk_amt"] or 1.0
    return {
        "ts": _ist(ts).isoformat(), "symbol": pos["symbol"], "sleeve": pos["sleeve"],
        "setup": pos["setup"], "side": side, "entry": entry, "exit": exit_fill, "qty": qty,
        "pnl": pnl, "r_multiple": round(pnl / risk_amt, 3), "fees": round(pos["entry_fees"] + exit_fees, 2),
        "reason": reason, "features": pos.get("features", {}),
    }


def _check_exit(pos: dict, bar, ts, broker, seg, hard_exit: str | None) -> dict | None:
    side, stop, target = pos["side"], pos["stop"], pos["target"]
    o, hi, lo, close = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])
    # P25: honest intrabar fills. A gap through the stop fills at the (worse) open —
    # stops aren't guaranteed; a limit target fills at the limit-or-better; a bar that
    # spans both resolves stop-first (conservative). Same exit bar/reason as the old
    # touch logic, just a truthful fill price instead of "filled exactly at the level".
    reason, fill = resolve_intrabar_exit(side, stop, target, o, hi, lo, broker.slippage_bps)
    if reason is not None:
        return _close_trade(pos, fill, ts, broker, seg, reason, exit_fill_price=fill)
    if hard_exit and _ist(ts).time() >= parse_hhmm(hard_exit):
        return _close_trade(pos, close, ts, broker, seg, "square_off_time")
    return None


async def run_backtest(params: BacktestParams, cfg=None) -> dict:
    cfg = cfg or get_config()
    if params.sleeve == "fno":
        from backtest.fno_engine import run_fno_backtest
        return attach_discrimination(await run_fno_backtest(params, cfg))
    if params.sleeve == "swing_stocks":
        from backtest.swing_engine import run_swing_backtest
        return attach_discrimination(await run_swing_backtest(params, cfg))
    if params.sleeve != "intraday_stocks":
        return {"error": f"backtest sleeve '{params.sleeve}' not supported (intraday_stocks | swing_stocks | fno)",
                "metrics": compute_metrics([], params.starting_capital), "trades": []}

    conf = ConfidenceModel(cfg)
    cost = CostModel(cfg.execution.cost_model)
    broker = BacktestBroker(cost, float(cfg.execution.slippage_bps))
    pipeline = IntradayPipeline(cfg)
    regime_cfg = (cfg.strategy.intraday_stocks or {}).get("regime")
    hard_exit = ((cfg.strategy.intraday_stocks or {}).get("time_gates") or {}).get("hard_exit", "15:20")
    daily_from = params.from_dt - timedelta(days=120)   # warmup for ADV/gap/200DMA
    trades: list[dict] = []
    skipped: list[str] = []

    # NIFTY daily once, for relative-strength features.
    from data.instruments import get_token
    nifty_tok = await get_token("NSE:NIFTY 50")
    nifty_daily = await win_load_index(nifty_tok, daily_from, params.to_dt) if nifty_tok else None

    for sym in params.symbols:
        inst = await resolve(sym)
        if not inst:
            skipped.append(sym)
            continue
        token = inst["instrument_token"]
        seg = cost.segment_key(params.sleeve, inst.get("instrument_type"))
        win = DataWindow()
        df5 = await win.load(token, "5m", datetime.combine(params.from_dt, datetime.min.time()),
                             datetime.combine(params.to_dt, datetime.max.time()))
        await win.load(token, "day", datetime.combine(daily_from, datetime.min.time()),
                       datetime.combine(params.to_dt, datetime.max.time()))
        if df5 is None or df5.empty:
            skipped.append(sym)
            continue

        open_pos: dict | None = None
        n = len(df5)
        for i in range(n):
            ts = df5.index[i]
            bar = df5.iloc[i]
            if open_pos is not None:
                done = _check_exit(open_pos, bar, ts, broker, seg, hard_exit)
                if done is not None:
                    trades.append(done)
                    open_pos = None
            if open_pos is not None or i + 1 >= n:
                continue  # one position per symbol; need a next bar to fill the entry

            df5_upto = df5.iloc[: i + 1]
            df_day_upto = win.slice(token, "day", ts)
            idx_upto = nifty_daily[nifty_daily.index <= ts] if nifty_daily is not None and not nifty_daily.empty else None
            ctx = intraday_context_from_frames(df5_upto, df_day_upto, _ist(ts),
                                               regime_cfg=regime_cfg, index_df=idx_upto)
            if ctx is None:
                continue
            res = await pipeline.evaluate(inst, ctx)
            if res.decision != PASS or res.signal is None:
                continue
            confidence = conf.score(res.gates)
            if not conf.passes(confidence):
                continue
            sig = res.signal
            sized = size_position(
                capital=params.starting_capital, per_trade_risk_pct=params.per_trade_pct,
                per_instrument_cap_pct=cfg.risk.per_instrument_cap_pct,
                entry_price=sig.entry, stop_price=sig.stop, lot_size=1,
                kind=InstrumentKind.EQUITY, confidence=confidence)
            if sized.rejected or sized.quantity <= 0:
                continue
            entry_ref = float(df5.iloc[i + 1]["open"])   # fill at next bar open
            # P25: an entry whose fill would breach the daily price band is rejected by
            # the exchange — model the honest no-fill on a big gap instead of trading it.
            ref_close = (float(df_day_upto["close"].iloc[-1])
                         if df_day_upto is not None and not df_day_upto.empty else 0.0)
            if price_band_breached(entry_ref, ref_close):
                continue
            fill = broker.entry_fill(sig.side, entry_ref)
            qty = sized.quantity
            open_pos = {
                "symbol": inst["tradingsymbol"], "sleeve": params.sleeve, "setup": sig.setup,
                "side": sig.side, "entry": fill, "qty": qty, "stop": sig.stop, "target": sig.target,
                "risk_amt": abs(sig.entry - sig.stop) * qty,
                "entry_fees": broker.fees(seg, sig.side, qty, fill),
                "features": signal_features(params.sleeve, ctx, confidence, res.gates, _ist(ts), signal=sig),
            }
        # square off anything still open at the last bar's close
        if open_pos is not None:
            trades.append(_close_trade(open_pos, float(df5.iloc[-1]["close"]), df5.index[-1],
                                       broker, seg, "eod"))

    metrics = compute_metrics(trades, params.starting_capital)
    log.info("backtest_complete", symbols=len(params.symbols), trades=len(trades),
             net=metrics["net_pnl"], skipped=len(skipped))
    return attach_discrimination({
        "metrics": metrics, "trades": trades, "skipped": skipped,
        "params": {"sleeve": params.sleeve, "symbols": params.symbols,
                   "from": str(params.from_dt), "to": str(params.to_dt),
                   "starting_capital": params.starting_capital, "per_trade_pct": params.per_trade_pct}})
