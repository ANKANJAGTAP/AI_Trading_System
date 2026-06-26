"""Backfill NSE F&O EOD bhavcopy (NIFTY + FINNIFTY index option chains) into the lake.

This is the historical option-chain substrate the F&O backtests + meta-model train on:
NSE publishes the FULL chain every trading day (every strike, OHLC + OI + settle),
including the contracts that have since expired — the one source a live-chain API
(Dhan included) can't reconstruct.

The existing `EODIngestionPipeline` already does quality-checks -> Parquet lake +
operational store -> manifest, idempotently, skipping non-trading days. This script
adds the missing piece: a cookie-warmed `requests.Session` downloader (NSE blocks bare
requests), picks the UDiFF vs legacy format by date, and drives the pipeline
month-by-month with progress.

    # run INSIDE the api container (DATAPLATFORM_HOME=/data/dataplatform is the lake volume):
    sudo docker compose exec -T api python scripts/bhavcopy_backfill.py --from 2023-06-01 --to 2026-06-20

Quarantined days (failed download / quality-rejected) are reported per month and never
silently dropped. Re-running is safe (idempotent per day). If NSE blocks the server's
datacenter IP (403s on every day), run this on a residential IP and sync the lake dir
(host ~/.aitrading_data) up to the server.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# NSE switched to the UDiFF "common bhavcopy" on 2024-07-08; older days are legacy.
UDIFF_CUTOVER = dt.date(2024, 7, 8)


# ---- pure helpers (stdlib only -> unit-testable, no network/lake) ------------
def bhavcopy_format_for(d: dt.date) -> str:
    """'udiff' for dates from the cutover onward, else 'legacy'. Pure."""
    return "udiff" if d >= UDIFF_CUTOVER else "legacy"


def month_windows(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """Split [start, end] into calendar-month chunks (clipped to the range). Pure."""
    out, cur = [], start
    while cur <= end:
        nxt = dt.date(cur.year + 1, 1, 1) if cur.month == 12 else dt.date(cur.year, cur.month + 1, 1)
        wend = min(nxt - dt.timedelta(days=1), end)
        out.append((cur, wend))
        cur = wend + dt.timedelta(days=1)
    return out


# ---- cookie-warmed adapter (heavy imports deferred) -------------------------
def _session_adapter(sleep: float, warm_pause: float):
    import requests
    from dataplatform.vendors.nse_bhavcopy import NSE_HEADERS, NSEBhavcopyAdapter

    class _SessionBhavcopy(NSEBhavcopyAdapter):
        """NSEBhavcopyAdapter that downloads via a cookie-warmed session + retries,
        and picks the bhavcopy format by date."""

        def __init__(self):
            super().__init__()
            self._s = None

        def _warm(self) -> None:
            s = requests.Session()
            s.headers.update(NSE_HEADERS)
            try:
                s.get("https://www.nseindia.com", timeout=30)
                time.sleep(warm_pause)
                s.get("https://www.nseindia.com/all-reports", timeout=30)
            except Exception:  # noqa: BLE001 — cookies may still be set; let the GET decide
                pass
            self._s = s

        def _download(self, url: str) -> bytes:
            if self._s is None:
                self._warm()
            resp = None
            for attempt in range(4):
                try:
                    resp = self._s.get(url, timeout=60,
                                       headers={"Referer": "https://www.nseindia.com/"})
                except Exception:  # noqa: BLE001 — transient network; back off + retry
                    if attempt == 3:
                        raise
                    time.sleep(2 * (attempt + 1))
                    continue
                if resp.status_code == 200:
                    return resp.content
                if resp.status_code == 404:                 # not published (holiday) -> miss
                    raise FileNotFoundError(f"404 {url}")
                if resp.status_code in (401, 403):           # cookie expired / blocked -> re-warm
                    self._warm()
                time.sleep(2 * (attempt + 1))
            raise RuntimeError(f"HTTP {resp.status_code if resp is not None else '??'} for {url}")

        def fetch_eod_fno(self, trade_date: dt.date):
            self.prefer = bhavcopy_format_for(trade_date)   # right format first (avoids a wasted 404)
            df = super().fetch_eod_fno(trade_date)
            time.sleep(sleep)                                # polite throttle between days
            return df

    return _SessionBhavcopy()


def _bse_session_adapter(sleep: float, warm_pause: float):
    """BSE SENSEX bhavcopy via a cookie-warmed session (BSE is UDiFF-only, no legacy)."""
    import requests
    from dataplatform.vendors.bse_bhavcopy import BSEBhavcopyAdapter

    class _SessionBSE(BSEBhavcopyAdapter):
        def __init__(self):
            super().__init__()
            self._s = None

        def _warm(self) -> None:
            s = requests.Session()
            s.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"})
            try:
                s.get("https://www.bseindia.com", timeout=30)
                time.sleep(warm_pause)
            except Exception:  # noqa: BLE001 — cookies may still be set; let the GET decide
                pass
            self._s = s

        def _download(self, url: str) -> bytes:
            if self._s is None:
                self._warm()
            resp = None
            for attempt in range(4):
                try:
                    resp = self._s.get(url, timeout=60,
                                       headers={"Referer": "https://www.bseindia.com/"})
                except Exception:  # noqa: BLE001 — transient network; back off + retry
                    if attempt == 3:
                        raise
                    time.sleep(2 * (attempt + 1))
                    continue
                if resp.status_code == 200:
                    return resp.content
                if resp.status_code == 404:                 # not published (holiday) -> miss
                    raise FileNotFoundError(f"404 {url}")
                if resp.status_code in (401, 403):
                    self._warm()
                time.sleep(2 * (attempt + 1))
            raise RuntimeError(f"HTTP {resp.status_code if resp is not None else '??'} for {url}")

        def fetch_eod_fno(self, trade_date: dt.date):
            df = super().fetch_eod_fno(trade_date)
            time.sleep(sleep)
            return df

    return _SessionBSE()


def main(args) -> int:
    from dataplatform.ingestion.eod_pipeline import EODIngestionPipeline

    try:
        start, end = dt.date.fromisoformat(args.from_date), dt.date.fromisoformat(args.to_date)
    except ValueError:
        print("ERROR: --from/--to must be YYYY-MM-DD")
        return 2
    if start > end:
        print("ERROR: --from must be on/before --to")
        return 2

    make = _bse_session_adapter if args.exchange == "bse" else _session_adapter
    syms = "SENSEX" if args.exchange == "bse" else "NIFTY+FINNIFTY+BANKNIFTY"
    pipe = EODIngestionPipeline(make(args.sleep, args.warm_pause))
    print(f"{args.exchange.upper()} bhavcopy backfill: {syms}  {start}..{end}  "
          f"({len(month_windows(start, end))} months) -> lake @ "
          f"{os.environ.get('DATAPLATFORM_HOME', '~/.aitrading_data')}")

    g_rows = g_ok = g_quar = 0
    for mstart, mend in month_windows(start, end):
        run = pipe.ingest_range(mstart, mend)
        ok = sum(1 for d in run.days if d.ok and d.rows > 0)
        quar = len(run.quarantined_days)
        g_rows += run.total_rows
        g_ok += ok
        g_quar += quar
        print(f"[{mstart:%Y-%m}] good_days={ok:2d} quarantined={quar:2d} rows={run.total_rows:7d}")
    print(f"\ndone: {g_rows} rows · {g_ok} good days · {g_quar} quarantined")
    if g_rows == 0:
        print(f"WARNING: 0 rows — {args.exchange.upper()} likely blocked this IP (403), or the "
              "URL pattern needs updating, or the range has no trading days. Try a residential "
              "IP and sync the lake dir up, or verify the bhavcopy URL.")
        return 1
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--exchange", choices=["nse", "bse"], default="nse",
                   help="nse = NIFTY/FINNIFTY/BANKNIFTY (default); bse = SENSEX")
    p.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--sleep", type=float, default=0.8, help="seconds between days (politeness)")
    p.add_argument("--warm-pause", dest="warm_pause", type=float, default=1.0,
                   help="seconds to wait after warming exchange cookies")
    raise SystemExit(main(p.parse_args()))
