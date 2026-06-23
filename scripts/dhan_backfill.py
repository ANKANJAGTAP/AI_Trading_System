"""Backfill candles from DhanHQ historical (free daily + intraday OHLCV) into the store.

Run ON THE SERVER (DHAN_ACCESS_TOKEN / DHAN_CLIENT_ID in `.env`). For each symbol it
resolves the Kite instrument_token (the candle key the engine/backtests use) and the
Dhan securityId (the query key), pulls bars, and upserts them. Dhan intraday gives
1/5/15/30/60-min for the last ~5 years — this fills the minute data the EOD bhavcopy
lake lacks (the reason intraday backtests returned zero trades).

    python scripts/dhan_backfill.py --symbols NSE:RELIANCE NSE:TCS --interval 5m \
        --from 2025-01-01 --to 2026-06-22 \
        --scrip-master https://images.dhan.co/api-data/api-scrip-master-detailed.csv

`--scrip-master` (CSV path or URL) maps tradingsymbol -> Dhan securityId. For a single
symbol you can skip it and pass --security-id directly.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.db import close_pool, init_pool  # noqa: E402
from common.logging import configure_logging  # noqa: E402
from data.instruments import get_token  # noqa: E402
from data.store import upsert_candles  # noqa: E402
from dataplatform.vendors.dhan import (DHAN_INTERVAL, DhanHistorical,  # noqa: E402
                                       dhan_to_candle_rows, parse_scrip_master)

_SEG = {"NSE": "NSE_EQ", "BSE": "BSE_EQ"}     # default exchangeSegment by symbol prefix


def _load_scrip_master(src: str) -> dict:
    if not src:
        return {}
    if src.startswith("http"):
        import requests
        return parse_scrip_master(requests.get(src, timeout=60).text)
    with open(src, encoding="utf-8", errors="ignore") as fh:
        return parse_scrip_master(fh.read())


async def _main(args) -> None:
    configure_logging()
    if not os.environ.get("DHAN_ACCESS_TOKEN"):
        print("ERROR: set DHAN_ACCESS_TOKEN (and DHAN_CLIENT_ID) in .env first")
        return
    daily = args.interval == "day"
    dhan_iv = DHAN_INTERVAL.get(args.interval)
    if not daily and not dhan_iv:
        print(f"ERROR: unsupported interval {args.interval} (use 1m/5m/15m/30m/60m or 'day')")
        return
    scrip = _load_scrip_master(args.scrip_master)
    dhan = DhanHistorical()
    await init_pool()
    try:
        total = 0
        for sym in args.symbols:
            exch, _, tsym = sym.partition(":")
            token = await get_token(sym)
            if not token:
                print(f"[skip] {sym}: no instrument_token (refresh the instruments master first)")
                continue
            sid = args.security_id or (scrip.get((exch.upper(), tsym.upper())) or {}).get("security_id")
            if not sid:
                print(f"[skip] {sym}: no Dhan securityId (pass --scrip-master or --security-id)")
                continue
            seg = args.segment or _SEG.get(exch.upper(), "NSE_EQ")
            try:
                if daily:
                    resp = dhan.daily(sid, seg, args.instrument, args.from_date, args.to_date)
                else:
                    resp = dhan.intraday(sid, seg, args.instrument, dhan_iv, args.from_date, args.to_date)
            except Exception as exc:  # noqa: BLE001 — report transport/HTTP failures plainly
                print(f"[fail] {sym}: {exc}")
                continue
            rows = dhan_to_candle_rows(resp, token, "day" if daily else args.interval)
            n = await upsert_candles(rows)
            total += n
            print(f"[ok]   {sym} (token {token}, dhan {sid}): {n} bars")
        print(f"done: {total} candle rows upserted")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", nargs="+", required=True, help="e.g. NSE:RELIANCE NSE:TCS")
    p.add_argument("--interval", default="5m", help="1m/5m/15m/30m/60m or 'day'")
    p.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD (intraday inclusive; daily non-inclusive)")
    p.add_argument("--scrip-master", default="", help="Dhan scrip-master CSV path or URL")
    p.add_argument("--security-id", default="", help="override Dhan securityId (single symbol)")
    p.add_argument("--segment", default="", help="override exchangeSegment (e.g. NSE_FNO, IDX_I)")
    p.add_argument("--instrument", default="EQUITY", help="Dhan instrument type (EQUITY/INDEX/...)")
    asyncio.run(_main(p.parse_args()))
