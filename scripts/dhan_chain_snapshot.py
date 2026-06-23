"""Record a live DhanHQ option-chain snapshot (real greeks/IV/OI/bid-ask).

Dhan's option chain is a LIVE snapshot, so this forward-records the chain rather
than backfilling history. Run ON THE SERVER (DHAN_ACCESS_TOKEN / DHAN_CLIENT_ID in
`.env`) during market hours. For each underlying it pulls the nearest expiries,
parses every CE/PE leg (greeks/IV/OI/volume/bid-ask) and writes them to a
timestamped CSV under the snapshot dir.

    python scripts/dhan_chain_snapshot.py --underlyings NIFTY FINNIFTY SENSEX --expiries 2

Dhan enforces ONE option-chain request every 3 seconds; `--sleep` (default 3.0)
honours that. `--lake` additionally pushes the canonical EOD rows through the
existing ingestion pipeline (needs the operational store/config).

⚠️ Index security ids/segments default to Dhan's annexure values; override any
that differ for your plan with repeated `--scrip NIFTY=13:IDX_I` flags.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataplatform.vendors.dhan_chain import (DhanChainAdapter,  # noqa: E402
                                             chain_rows_to_records)


def _parse_scrip_overrides(items) -> dict:
    """['NIFTY=13:IDX_I', ...] -> {'NIFTY': (13, 'IDX_I')}."""
    out = {}
    for it in items or []:
        sym, _, rest = it.partition("=")
        sid, _, seg = rest.partition(":")
        out[sym.upper()] = (int(sid), seg or "IDX_I")
    return out


def main(args) -> None:
    if not (os.environ.get("DHAN_ACCESS_TOKEN") and os.environ.get("DHAN_CLIENT_ID")):
        print("ERROR: set DHAN_ACCESS_TOKEN and DHAN_CLIENT_ID in .env first")
        return
    adapter = DhanChainAdapter(
        underlyings=tuple(args.underlyings),
        scrip_map=_parse_scrip_overrides(args.scrip),
        n_expiries=args.expiries,
    )
    asof = dt.date.today()
    all_rows: list[dict] = []
    first_call = True
    for sym in args.underlyings:
        try:
            expiries = adapter.expiry_list(sym)[: args.expiries]
        except Exception as exc:  # noqa: BLE001 — report plainly, keep going
            print(f"[fail] {sym} expirylist: {exc}")
            continue
        sym_rows = 0
        for exp in expiries:
            if not first_call:
                time.sleep(args.sleep)            # respect the 1-req/3s chain limit
            first_call = False
            try:
                rows = adapter.fetch_chain_rows(sym, exp, asof=asof)
            except Exception as exc:  # noqa: BLE001
                print(f"[fail] {sym} {exp}: {exc}")
                continue
            all_rows.extend(rows)
            sym_rows += len(rows)
            spot = rows[0]["underlying_ltp"] if rows else None
            print(f"[ok]   {sym} {exp}: {len(rows)} legs (spot {spot})")
        print(f"       {sym}: {sym_rows} legs total")

    if not all_rows:
        print("no rows pulled — check the Data API subscription / market hours / scrip ids")
        return

    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"dhan_chain_{asof.isoformat()}_{int(time.time())}.csv")
    records = chain_rows_to_records(all_rows)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
    print(f"done: {len(records)} legs -> {out_path}")

    if args.lake:
        from dataplatform.backfill import run_backfill
        run = run_backfill(adapter, asof, asof)
        print(f"lake: {getattr(run, 'total_rows', '?')} canonical rows ingested")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--underlyings", nargs="+", default=["NIFTY", "FINNIFTY", "SENSEX"])
    p.add_argument("--expiries", type=int, default=2, help="nearest N expiries per underlying")
    p.add_argument("--scrip", nargs="*", default=[], help="override scrip ids e.g. NIFTY=13:IDX_I")
    p.add_argument("--out-dir", default="data/option_chains", help="snapshot CSV output dir")
    p.add_argument("--sleep", type=float, default=3.0, help="seconds between chain calls (>=3)")
    p.add_argument("--lake", action="store_true", help="also ingest canonical EOD rows via the pipeline")
    main(p.parse_args())
