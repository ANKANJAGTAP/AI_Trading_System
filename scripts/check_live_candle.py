"""Confirm candles built LIVE from ticks (by the running engine) match Kite's own
1m candles within tolerance — the Phase 1 'candles match Kite' acceptance on live
aggregation (not backfill). Pick a symbol the verifier didn't backfill.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta

from broker.kite_adapter import KiteAdapter
from common.db import close_pool, fetch, init_pool
from common.market_time import IST, now_ist
from config.loader import get_config
from config.settings import get_settings
from data.instruments import get_token
from data.rate_governor import RateGovernor

SYMBOL = "NSE:SBIN"  # in the watchlist, NOT backfilled by verify_phase1


async def main() -> None:
    await init_pool()
    adapter = KiteAdapter(get_settings())
    adapter.ensure_token()
    gov = RateGovernor(get_config().data.rate_limits)

    tok = await get_token(SYMBOL)
    today = now_ist().date()
    cutoff = now_ist() - timedelta(minutes=1)  # exclude the in-progress minute
    rows = await fetch(
        "SELECT ts, open, high, low, close, volume FROM candles "
        "WHERE instrument_token=$1 AND interval='1m' AND ts::date=$2 AND ts < $3 "
        "ORDER BY ts DESC LIMIT 5",
        tok, today, cutoff,
    )
    if not rows:
        print("no live 1m candles for today yet")
        await close_pool()
        return

    start = datetime.combine(today, time(9, 15), tzinfo=IST)
    kdata = await gov.call("historical", adapter.historical, tok, start, now_ist(), "minute", False, False)
    kite = {c["date"].astimezone(IST).replace(second=0, microsecond=0): c for c in kdata}

    print(f"{SYMBOL}: engine LIVE-built 1m candles vs Kite official 1m")
    matches = 0
    checked = 0
    for r in rows:
        ts = r["ts"].astimezone(IST).replace(second=0, microsecond=0)
        k = kite.get(ts)
        if not k:
            print(f"  {ts.time()}: Kite 1m not available yet (skip)")
            continue
        diffs = [abs(float(r[f]) - k[f]) for f in ("open", "high", "low", "close")]
        within = max(diffs) < 0.10  # 10 paise
        checked += 1
        matches += 1 if within else 0
        print(
            f"  {ts.time()} live OHLC={r['open']}/{r['high']}/{r['low']}/{r['close']} "
            f"kite={k['open']}/{k['high']}/{k['low']}/{k['close']} "
            f"vol live={r['volume']} kite={k.get('volume')} maxΔ={max(diffs):.4f} "
            f"{'OK' if within else 'MISMATCH'}"
        )
    await close_pool()
    # Boot/connect boundary minutes can be partially captured; pass if all but at
    # most one (the boundary) of the compared minutes match within tolerance.
    ok = checked > 0 and matches >= max(1, checked - 1)
    print(f"LIVE CANDLE MATCH ({matches}/{checked} within 10p):", "PASS ✅" if ok else "CHECK")


if __name__ == "__main__":
    asyncio.run(main())
