"""Phase 6b acceptance (frontend_v2 data surface). Exercises the new + enriched
dashboard endpoints via the service layer in-process: Market, Chart, Option Chain,
Analytics, Rejection analytics, Layouts, plus enriched account/pnl/positions/
sleeves/risk/health. Seeds + self-cleans by correlation_id; safe alongside the engine.
"""
from __future__ import annotations

import asyncio
import sys
import uuid

from api import analytics as an
from api import marketdata, services
from common.db import close_pool, execute, fetchval, init_pool
from common.logging import configure_logging
from data.instruments import get_token

CORR = str(uuid.uuid4())
CORR_R = str(uuid.uuid4())


async def seed():
    tok = await get_token("NSE:RELIANCE") or 738561
    sid = await fetchval(
        "INSERT INTO signals (correlation_id, sleeve, instrument_token, tradingsymbol, setup, side, "
        "confidence, decision, reason) VALUES ($1::uuid,'intraday_stocks',$2,'TESTP6B','orb','BUY',0.8,'PASS','seed') "
        "RETURNING id", CORR, tok)
    for n, p, s in [("liquidity", True, 1.0), ("regime", True, 0.9), ("confirmation", True, 0.8)]:
        await execute("INSERT INTO gate_results (signal_id, correlation_id, gate_name, passed, score, detail) "
                      "VALUES ($1,$2::uuid,$3,$4,$5,'{}'::jsonb)", sid, CORR, n, p, s)
    # a rejected signal (for rejection analytics)
    rid = await fetchval(
        "INSERT INTO signals (correlation_id, sleeve, instrument_token, tradingsymbol, setup, side, "
        "confidence, decision, reason) VALUES ($1::uuid,'intraday_stocks',$2,'TESTP6R','orb','BUY',0.0,'REJECT',"
        "'choppy regime (breakouts disabled)') RETURNING id", CORR_R, tok)
    for n, p in [("liquidity", True), ("time_window", True), ("regime", False)]:
        await execute("INSERT INTO gate_results (signal_id, correlation_id, gate_name, passed, score, detail) "
                      "VALUES ($1,$2::uuid,$3,$4,0.5,'{}'::jsonb)", rid, CORR_R, n, p)
    # closed (R-multiple 2.0) + open (mae/mfe) positions today
    await execute("INSERT INTO positions (correlation_id, mode, sleeve, instrument_token, tradingsymbol, side, "
                  "quantity, entry_price, average_price, stop_price, target_price, r_rupees, status, realized_pnl, "
                  "closed_at) VALUES ($1::uuid,'simulated_fill','intraday_stocks',$2,'TESTP6B','BUY',10,100,100,95,"
                  "110,300,'closed',600, now())", CORR, tok)
    await execute("INSERT INTO positions (correlation_id, mode, sleeve, instrument_token, tradingsymbol, side, "
                  "quantity, entry_price, average_price, stop_price, target_price, r_rupees, status, "
                  "unrealized_pnl, mae, mfe) VALUES ($1::uuid,'simulated_fill','intraday_stocks',$2,'TESTP6B','BUY',"
                  "10,100,100,95,110,300,'open',150,-80,200)", CORR, tok)


async def checks() -> dict:
    r = {}
    acct = await services.account()
    r["account_used_margin"] = ("used_margin" in acct, f"used_margin={acct.get('used_margin')}")

    pnl = await services.pnl_today()
    r["pnl_equity_curve"] = (isinstance(pnl.get("equity_curve"), list) and len(pnl["equity_curve"]) >= 1,
                             f"points={len(pnl.get('equity_curve', []))}")

    pos = await services.positions()
    mine = next((p for p in pos if p.get("instrument") == "TESTP6B" and p.get("side") == "BUY"), None)
    r["positions_enriched"] = (mine is not None and all(k in mine for k in ("R_multiple", "mae", "mfe", "spark", "opened_at")),
                               f"R_mult={mine and mine.get('R_multiple')} mae={mine and mine.get('mae')} "
                               f"spark_len={mine and len(mine.get('spark') or [])} opened_at={mine and bool(mine.get('opened_at'))}")

    sl = await services.sleeves()
    r["sleeves_enriched"] = (len(sl) == 4 and all(k in sl[0] for k in ("curve", "wins", "losses", "avg_R")),
                             f"keys={[k for k in ('curve','wins','losses','avg_R') if k in (sl[0] if sl else {})]}")

    rk = await services.risk()
    r["risk_enriched"] = (all(k in rk for k in ("correlation_matrix", "exposure", "drawdown_curve", "killswitch_history")),
                          f"has={[k for k in ('correlation_matrix','exposure','drawdown_curve','killswitch_history') if k in rk]}")

    hl = await services.health()
    r["health_enriched"] = ("token_expiry" in hl and "error_rate" in hl,
                            f"token={hl.get('token')} error_rate={hl.get('error_rate')}")

    ana = await an.analytics("all")
    r["analytics"] = (ana["kpis"]["trades"] >= 1 and "equity_curve" in ana and "by_sleeve" in ana
                      and "r_histogram" in ana,
                      f"trades={ana['kpis']['trades']} win_rate={ana['kpis']['win_rate']} "
                      f"expectancy_R={ana['kpis']['expectancy_R']} dataset={ana['dataset']}")

    rej = await an.rejections(48)
    gates = [g["gate"] for g in rej["by_gate"]]
    r["rejection_analytics"] = ("regime" in gates and "by_reason" in rej and "near_misses" in rej,
                                f"by_gate={gates[:4]} reasons={len(rej['by_reason'])} near={len(rej['near_misses'])}")

    await services.layouts_put("verify_layout", {"panes": ["pnl", "positions"]})
    lays = await services.layouts_get()
    r["layouts_roundtrip"] = (any(x["name"] == "verify_layout" for x in lays), f"layouts={[x['name'] for x in lays]}")

    mk = await marketdata.market()
    first = mk[0] if mk else {}
    r["market_grid"] = (len(mk) >= 1 and all(k in first for k in ("instrument", "ltp", "rvol", "vwap_dist", "day_range")),
                        f"rows={len(mk)} sample={first.get('instrument')} ltp={first.get('ltp')}")

    ch = await marketdata.chart("RELIANCE")
    r["chart"] = (isinstance(ch.get("candles"), list) and all(k in ch for k in ("overlays", "markers", "depth")),
                  f"candles={len(ch.get('candles', []))} markers={len(ch.get('markers', []))}")

    oc = await marketdata.optionchain("NIFTY")
    r["optionchain"] = ("underlying" in oc and ("strikes" in oc),
                        f"strikes={len(oc.get('strikes', []))} pcr={oc.get('pcr')} max_pain={oc.get('max_pain')} "
                        f"err={oc.get('error')}")
    return r


async def cleanup():
    for cid in (CORR, CORR_R):
        for t in ("gate_results", "audit_log", "positions", "signals"):
            try:
                await execute(f"DELETE FROM {t} WHERE correlation_id=$1::uuid", cid)
            except Exception:
                pass
    try:
        await execute("DELETE FROM dashboard_layouts WHERE name='verify_layout'")
    except Exception:
        pass


async def main():
    configure_logging()
    await init_pool()
    results = {}
    try:
        await seed()
        results = await checks()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        results["ERROR"] = (False, f"{type(exc).__name__}: {exc}")
    finally:
        await cleanup()
        await close_pool()
    print("\n=== PHASE 6b ACCEPTANCE (frontend_v2 data surface) ===")
    overall = True
    for name, (passed, detail) in results.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
        overall = overall and passed
    print("RESULT:", "PASS ✅" if overall and results else "FAIL ❌")
    sys.exit(0 if overall and results else 1)


if __name__ == "__main__":
    asyncio.run(main())
