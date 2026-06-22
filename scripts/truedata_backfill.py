"""CLI: backfill intraday candles from TrueData into the candle store.

Run ON THE SERVER (TrueData creds in `.env`, SDK installed via requirements). For
each symbol it resolves the instrument_token, pulls bars via TrueData `TD_hist`, and
upserts them into `candles` — giving the intraday/swing engines and backtests the
minute data the EOD bhavcopy lake lacks (this is what was making intraday backtests
return zero trades).

    python scripts/truedata_backfill.py --symbols NSE:RELIANCE NSE:TCS --interval 5m --duration "30 D"

Credentials come from the environment only (TRUEDATA_USERNAME / TRUEDATA_PASSWORD) —
never hardcode the trial id/password.
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
from dataplatform.vendors.truedata import TrueDataAdapter, bars_to_candle_rows  # noqa: E402

# system interval tag -> TrueData bar_size string
_BAR = {"1m": "1 min", "5m": "5 min", "15m": "15 min", "30m": "30 min", "60m": "60 min"}


def _td_symbol(exch_symbol: str) -> str:
    """'NSE:RELIANCE' -> 'RELIANCE'; pass plain symbols / 'NIFTY-I' through unchanged."""
    return exch_symbol.split(":", 1)[-1]


async def _main(args) -> None:
    configure_logging()
    if not (os.environ.get("TRUEDATA_USERNAME") and os.environ.get("TRUEDATA_PASSWORD")):
        print("ERROR: set TRUEDATA_USERNAME / TRUEDATA_PASSWORD in .env first")
        return
    bar_size = _BAR.get(args.interval, args.interval)
    adapter = TrueDataAdapter()
    await init_pool()
    try:
        total = 0
        for sym in args.symbols:
            token = await get_token(sym)
            if not token:
                print(f"[skip] {sym}: no instrument_token (refresh the instruments master first)")
                continue
            try:
                bars = adapter.intraday_bars(_td_symbol(sym), duration=args.duration, bar_size=bar_size)
            except Exception as exc:  # noqa: BLE001 — report any SDK/transport failure plainly
                print(f"[fail] {sym}: {exc}")
                continue
            rows = bars_to_candle_rows(bars, token, args.interval)
            n = await upsert_candles(rows)
            total += n
            print(f"[ok]   {sym} (token {token}): {n} {args.interval} bars")
        print(f"done: {total} candle rows upserted")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", nargs="+", required=True, help="e.g. NSE:RELIANCE NSE:TCS")
    p.add_argument("--interval", default="5m", help="system interval tag: 1m/5m/15m/30m/60m")
    p.add_argument("--duration", default="30 D", help="TrueData duration, e.g. '30 D' / '5 D'")
    asyncio.run(_main(p.parse_args()))
