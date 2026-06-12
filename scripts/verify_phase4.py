"""Phase 4 acceptance (Strategy Pipelines). Each pipeline -> correct PASS/REJECT
with a full per-gate trail; known disqualifying conditions rejected; F&O enforces
defined-risk only (no naked selling). Plus a real-candle smoke run.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta

from common.db import close_pool, init_pool
from common.logging import configure_logging, get_logger
from config.loader import get_config
from data import indicators
from data.instruments import get_token
from data.store import load_candles_df
from strategies.base import PASS, REJECT
from strategies.fno import FnoContext, FnoPipeline
from strategies.intraday import IntradayContext, IntradayPipeline
from strategies.mcx import McxIntradayPipeline
from strategies.swing import SwingContext, SwingPipeline

log = get_logger("verify_phase4")
cfg = get_config()
EQ = {"instrument_token": 1, "tradingsymbol": "TEST", "exchange": "NSE", "lot_size": 1, "instrument_type": "EQ"}
NIFTY = {"tradingsymbol": "NIFTY", "exchange": "NFO", "instrument_type": "CE", "lot_size": 50}


def _intra(**kw):
    base = dict(last_price=105, or_high=104, or_low=100, vwap=103, rvol=2.2, daily_adv=3_000_000,
                spread_pct=0.05, gap_pct=0.8, regime="trending_up", sector_strong=True, now_window_ok=True)
    base.update(kw)
    return IntradayContext(**base)


async def c_intraday_pass():
    r = await IntradayPipeline(cfg).evaluate(EQ, _intra())
    ok = r.decision == PASS and r.signal and r.signal.side == "BUY" and r.signal.setup == "orb"
    s = r.signal
    return ok, f"{r.decision} setup={s and s.setup} entry={s and s.entry} stop={s and s.stop} target={s and s.target} conf={r.confidence}"


async def c_intraday_reject_choppy():
    r = await IntradayPipeline(cfg).evaluate(EQ, _intra(regime="choppy"))
    return (r.decision == REJECT and "choppy" in (r.reason or "")), f"{r.decision}: {r.reason}"


async def c_intraday_reject_rvol():
    r = await IntradayPipeline(cfg).evaluate(EQ, _intra(rvol=0.8))
    return (r.decision == REJECT and "confirmation" in (r.reason or "")), f"{r.decision}: {r.reason}"


async def c_fno_lowiv_debit():
    ctx = FnoContext(spot=23400, iv=0.12, iv_rank=10, dte=7, direction="bullish", lot_size=50,
                     expiry=date.today() + timedelta(days=7))
    r = await FnoPipeline(cfg).evaluate(NIFTY, ctx)
    st = r.signal and r.signal.detail.get("structure")
    ok = r.decision == PASS and st and "debit" in st["type"] and st["max_loss_per_lot"] > 0
    return ok, f"{r.decision} struct={st and st['type']} max_loss/lot=Rs{st and st['max_loss_per_lot']}"


async def c_fno_highiv_credit_defined_risk():
    ctx = FnoContext(spot=23400, iv=0.30, iv_rank=80, dte=25, direction="bearish", lot_size=50,
                     expiry=date.today() + timedelta(days=25))
    r = await FnoPipeline(cfg).evaluate(NIFTY, ctx)
    st = r.signal and r.signal.detail.get("structure")
    # high IV -> credit spread that is DEFINED-RISK (has a long hedge leg), never naked
    ok = (r.decision == PASS and st and "credit" in st["type"]
          and st.get("long_leg") and st["max_loss_per_lot"] > 0
          and r.signal.detail.get("no_naked_selling") is True)
    return ok, f"{r.decision} struct={st and st['type']} long_hedge={st and st.get('long_leg')} max_loss/lot=Rs{st and st['max_loss_per_lot']}"


async def c_fno_reject_0dte():
    ctx = FnoContext(spot=23400, iv=0.30, iv_rank=80, dte=0, direction="bearish", lot_size=50,
                     expiry=date.today())
    r = await FnoPipeline(cfg).evaluate(NIFTY, ctx)
    return (r.decision == REJECT and "DTE" in (r.reason or "")), f"{r.decision}: {r.reason}"


async def c_fno_reject_banned():
    ctx = FnoContext(spot=23400, iv=0.30, iv_rank=80, dte=25, direction="bearish", lot_size=50,
                     expiry=date.today() + timedelta(days=25), is_banned=True)
    r = await FnoPipeline(cfg).evaluate(NIFTY, ctx)
    return (r.decision == REJECT and "ban" in (r.reason or "").lower()), f"{r.decision}: {r.reason}"


_GOOD_FUND = {"market_cap_cr": 80000, "roe": 22, "revenue_growth": 18, "eps_growth": 20,
              "debt_equity": 0.2, "promoter_holding_trend": "stable", "avg_daily_volume": 5_000_000}


async def c_swing_pass():
    ctx = SwingContext(last_price=1500, sma200=1300, atr=30, market_uptrend=True, sector_strong=True,
                       setup_ok=True, setup="breakout", fundamentals=_GOOD_FUND)
    r = await SwingPipeline(cfg).evaluate(EQ, ctx)
    s = r.signal
    ok = r.decision == PASS and s and s.stop < s.entry < s.target
    return ok, f"{r.decision} entry={s and s.entry} stop={s and s.stop} target={s and s.target} conf={r.confidence}"


async def c_swing_reject_fundamentals():
    junk = {"market_cap_cr": 800, "roe": 5, "revenue_growth": 2, "eps_growth": 1,
            "debt_equity": 1.5, "promoter_holding_trend": "falling", "avg_daily_volume": 50000}
    ctx = SwingContext(last_price=1500, sma200=1300, atr=30, market_uptrend=True, sector_strong=True,
                       setup_ok=True, fundamentals=junk)
    r = await SwingPipeline(cfg).evaluate(EQ, ctx)
    return (r.decision == REJECT and "fundamentals" in (r.reason or "")), f"{r.decision}: {r.reason}"


async def c_swing_reject_below_200dma():
    ctx = SwingContext(last_price=1200, sma200=1300, atr=30, market_uptrend=True, sector_strong=True,
                       setup_ok=True, fundamentals=_GOOD_FUND)
    r = await SwingPipeline(cfg).evaluate(EQ, ctx)
    return (r.decision == REJECT and "200" in (r.reason or "")), f"{r.decision}: {r.reason}"


async def c_mcx_intraday_pass():
    ctx = _intra(last_price=72000, or_high=71800, or_low=71000, vwap=71500, rvol=2.0, sector_strong=False)
    r = await McxIntradayPipeline(cfg).evaluate(
        {"tradingsymbol": "GOLD", "exchange": "MCX", "instrument_type": "FUT", "lot_size": 100}, ctx)
    ok = r.decision == PASS and r.signal and r.signal.sleeve == "mcx_commodities"
    return ok, f"{r.decision} sleeve={r.signal and r.signal.sleeve} setup={r.signal and r.signal.setup} (no sector filter)"


async def c_real_candle_smoke():
    tok = await get_token("NSE:RELIANCE")
    daily = await load_candles_df(tok, "day", 400)
    if len(daily) < 200:
        return True, "insufficient real daily candles (skip)"
    d = indicators.add_core_indicators(daily, intraday=False)
    last = d.iloc[-1]
    ctx = SwingContext(last_price=float(last["close"]), sma200=float(last["sma200"]),
                       atr=float(last["atr14"]), market_uptrend=True, sector_strong=True,
                       setup_ok=True, fundamentals=_GOOD_FUND)
    r = await SwingPipeline(cfg).evaluate({"tradingsymbol": "RELIANCE"}, ctx)
    return True, (f"swing[RELIANCE real daily: close={last['close']:.1f} sma200={last['sma200']:.1f}] "
                  f"-> {r.decision} ({r.reason or 'signal generated'}); trail={[g['name'] for g in r.trail]}")


async def main():
    configure_logging()
    await init_pool()
    checks = {
        "intraday_PASS_orb": c_intraday_pass(),
        "intraday_REJECT_choppy": c_intraday_reject_choppy(),
        "intraday_REJECT_rvol": c_intraday_reject_rvol(),
        "fno_PASS_lowIV_debit": c_fno_lowiv_debit(),
        "fno_PASS_highIV_credit_DEFINED_RISK": c_fno_highiv_credit_defined_risk(),
        "fno_REJECT_0dte": c_fno_reject_0dte(),
        "fno_REJECT_banned": c_fno_reject_banned(),
        "swing_PASS": c_swing_pass(),
        "swing_REJECT_fundamentals": c_swing_reject_fundamentals(),
        "swing_REJECT_below_200dma": c_swing_reject_below_200dma(),
        "mcx_intraday_PASS": c_mcx_intraday_pass(),
        "real_candle_smoke": c_real_candle_smoke(),
    }
    results = {}
    for name, coro in checks.items():
        try:
            results[name] = await coro
        except Exception as exc:
            results[name] = (False, f"error: {exc}")
    await close_pool()

    print("\n=== PHASE 4 ACCEPTANCE ===")
    overall = True
    for name, (passed, detail) in results.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
        overall = overall and passed
    print("==========================")
    print("RESULT:", "PASS ✅" if overall else "FAIL ❌")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    asyncio.run(main())
