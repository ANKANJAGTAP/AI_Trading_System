"""
One call that compounds the F&O history forward: pull the last few sessions and
write them to BOTH the Parquet lake (research) and the operational store
(TimescaleDB, when TIMESCALE_DSN is set — the SAME database the live engine uses).

This is the single entry point shared by:
  * the daily cron (dataplatform/daily_capture.sh), and
  * the live engine's optional scheduled ingestion job (engine/main.py).

It is deliberately BEST-EFFORT and side-effect-safe: every failure path returns
a dict with an "error" key instead of raising, so a caller embedded in the live
engine can never be brought down by a data pull. Re-ingesting a date is
idempotent (upsert on the natural key) in both the lake and the store.
"""
from __future__ import annotations

import datetime as dt
import os

from ..storage import OperationalStore, ParquetLake
from .eod_pipeline import EODIngestionPipeline


def _build_kite_adapter(refresh: bool = False):
    """Build a ready KiteHistoricalAdapter from the stored token, or None.

    Mirrors pull_kite_data but never exits the process — on any problem it
    returns None so the caller degrades gracefully.
    """
    try:
        from ..kite_auth import load_token, refresh_from_env
        from ..vendors import KiteHistoricalAdapter
    except Exception:
        return None
    path = os.environ.get("TOKEN_STORE_PATH", ".secrets/kite_token.json")
    key = os.environ.get("TOKEN_ENCRYPTION_KEY") or None
    try:
        if refresh or load_token(path, key) is None:
            refresh_from_env()                      # login + TOTP (best-effort)
    except Exception:
        pass                                        # maybe a usable token is already stored
    try:
        kite = KiteHistoricalAdapter.from_token_store()
        if not kite.available():
            return None
        kite.load_instruments(("NFO", "BFO"))
        return kite
    except Exception:
        return None


def run_daily_ingestion(days_back: int = 3, source: str = "kite",
                        underlyings=None, refresh_token: bool = False) -> dict:
    """Ingest the last `days_back` sessions into the lake + operational store.

    Returns a summary dict (never raises). `source` is "kite" (real) or
    "synthetic" (plumbing test). The OperationalStore auto-selects TimescaleDB
    when TIMESCALE_DSN is set, else a local SQLite mirror.
    """
    underlyings = tuple(underlyings) if underlyings else ("NIFTY", "FINNIFTY", "SENSEX")
    end = dt.date.today()
    start = end - dt.timedelta(days=max(1, int(days_back)))

    try:
        if source == "kite":
            adapter = _build_kite_adapter(refresh_token)
            if adapter is None:
                return {"error": "kite adapter not ready (token/creds/instruments)",
                        "source": source, "rows": 0}
        else:
            from ..vendors import SyntheticEODAdapter
            adapter = SyntheticEODAdapter(underlyings=underlyings)

        store = OperationalStore()                  # TIMESCALE_DSN -> shared DB, else SQLite
        pipeline = EODIngestionPipeline(adapter, ParquetLake(), store)
        run = pipeline.ingest_range(start, end)
        return {
            "source": run.source,
            "store_backend": store.backend,
            "start": str(start), "end": str(end),
            "rows": run.total_rows,
            "days": len(run.days),
            "quarantined": [str(d) for d in run.quarantined_days],
            "manifest": str(run.manifest_path) if run.manifest_path else None,
        }
    except Exception as exc:                         # belt-and-suspenders: never raise
        return {"error": f"{type(exc).__name__}: {exc}", "source": source, "rows": 0}


def main(argv=None) -> None:
    import argparse
    import json
    p = argparse.ArgumentParser(prog="dataplatform.ingestion.daily")
    p.add_argument("--days-back", type=int, default=3)
    p.add_argument("--source", choices=["kite", "synthetic"], default="kite")
    p.add_argument("--underlyings", default="NIFTY,FINNIFTY,SENSEX")
    p.add_argument("--refresh-token", action="store_true")
    a = p.parse_args(argv)
    res = run_daily_ingestion(
        days_back=a.days_back, source=a.source,
        underlyings=[u.strip() for u in a.underlyings.split(",") if u.strip()],
        refresh_token=a.refresh_token,
    )
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
