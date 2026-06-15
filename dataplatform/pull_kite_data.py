"""
One-command historical data pull into the lake.

Runs on YOUR machine with YOUR credentials (read from the environment) — it
authenticates to Zerodha itself; no credentials are handled anywhere else.

    set -a; source .env; set +a
    # dry run first (no creds needed) to confirm the plumbing:
    python -m dataplatform.pull_kite_data --source synthetic --start 2026-06-01 --end 2026-06-05
    # then the real pull:
    python -m dataplatform.pull_kite_data --source kite --start 2026-04-01 --end 2026-06-15

Notes:
  * `--source kite` mints today's access token if needed (login + TOTP), loads
    the NFO/BFO instrument master, and backfills the front expiries' chains.
  * Kite serves ACTIVE contracts only, so start with a recent range to validate
    symbology before going wider.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _kite_adapter(refresh: bool):
    from .kite_auth import load_token, refresh_from_env
    from .vendors import KiteHistoricalAdapter

    path = os.environ.get("TOKEN_STORE_PATH", ".secrets/kite_token.json")
    key = os.environ.get("TOKEN_ENCRYPTION_KEY") or None

    if refresh or load_token(path, key) is None:
        print("[kite] minting today's access token (login + TOTP) ...")
        refresh_from_env()
        print("[kite] token stored.")

    kite = KiteHistoricalAdapter.from_token_store()
    if not kite.available():
        sys.exit("[kite] not ready — check kiteconnect is installed, env creds are "
                 "set, and the token minted (see KITE.md).")
    print("[kite] loading instrument master (NFO + BFO) ...")
    kite.load_instruments(("NFO", "BFO"))
    return kite


def main(argv=None):
    p = argparse.ArgumentParser(prog="pull_kite_data")
    p.add_argument("--source", choices=["kite", "synthetic"], default="synthetic")
    p.add_argument("--start", required=True, type=_date)
    p.add_argument("--end", required=True, type=_date)
    p.add_argument("--underlyings", default="NIFTY,FINNIFTY,SENSEX")
    p.add_argument("--refresh-token", action="store_true",
                   help="force a fresh Kite token even if one is stored")
    args = p.parse_args(argv)

    underlyings = tuple(u.strip() for u in args.underlyings.split(",") if u.strip())

    if args.source == "kite":
        adapter = _kite_adapter(args.refresh_token)
    else:
        from .vendors import SyntheticEODAdapter
        adapter = SyntheticEODAdapter(underlyings=underlyings)

    from .backfill import run_backfill
    print(f"[backfill] {args.source} {args.start} -> {args.end} ...")
    run = run_backfill(adapter, args.start, args.end)
    print(f"[backfill] rows={run.total_rows} days={len(run.days)} "
          f"quarantined={run.quarantined_days}")
    print(f"[backfill] manifest: {run.manifest_path}")

    # quick verification: read back from the lake
    from .storage import ParquetLake
    lake = ParquetLake()
    for u in underlyings:
        df = lake.read_eod(underlying=u, start=args.start, end=args.end)
        if len(df):
            fut = (df["instrument"] == "FUT").sum()
            opt = (df["instrument"] == "OPT").sum()
            print(f"  [lake] {u:9} rows={len(df):>7}  (FUT={fut}, OPT={opt})")
        else:
            print(f"  [lake] {u:9} no rows")
    print("Done. Point features/ml/backtest at the lake next.")


if __name__ == "__main__":
    main()
