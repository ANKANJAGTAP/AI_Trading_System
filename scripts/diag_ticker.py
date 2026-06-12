"""Bare KiteTicker streaming probe (no asyncio). Counts tick batches over 30s to
isolate whether KiteTicker streams continuously vs only a connect snapshot."""
from __future__ import annotations

import time

from broker.kite_adapter import KiteAdapter
from config.settings import get_settings

TOKENS = [738561, 256265, 779521]  # RELIANCE, NIFTY BANK, SBIN

a = KiteAdapter(get_settings())
a.ensure_token()
from kiteconnect import KiteTicker

kt = KiteTicker(a.s.kite_api_key, a._access_token)
state = {"batches": 0, "ticks": 0}


def on_ticks(ws, ticks):
    state["batches"] += 1
    state["ticks"] += len(ticks)
    if state["batches"] <= 8 or state["batches"] % 25 == 0:
        t0 = ticks[0] if ticks else {}
        print(f"  batch {state['batches']}: ltp={t0.get('last_price')} "
              f"exch_ts={t0.get('exchange_timestamp')} ltt={t0.get('last_trade_time')} "
              f"mode={t0.get('mode')}", flush=True)


def on_connect(ws, response):
    print("connected -> subscribing", flush=True)
    ws.subscribe(TOKENS)
    ws.set_mode(ws.MODE_FULL, TOKENS)


def on_close(ws, code, reason):
    print(f"closed code={code} reason={reason}", flush=True)


def on_error(ws, code, reason):
    print(f"error code={code} reason={reason}", flush=True)


kt.on_ticks = on_ticks
kt.on_connect = on_connect
kt.on_close = on_close
kt.on_error = on_error

print("connecting (threaded)...", flush=True)
kt.connect(threaded=True)
time.sleep(15)
print(f"\nTOTAL over 30s: batches={state['batches']} ticks={state['ticks']}", flush=True)
print("VERDICT:", "STREAMS CONTINUOUSLY" if state["batches"] > 3 else "SNAPSHOT-ONLY / NOT STREAMING")
