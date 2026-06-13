"""
Command-line entry point.

  python -m dataplatform.cli ingest --source synthetic --start 2026-06-01 --end 2026-06-05
  python -m dataplatform.cli ingest --source nse --start 2024-07-01 --end 2024-07-05
  python -m dataplatform.cli setup-report      # show specs/rules still needing verification
  python -m dataplatform.cli expiries --underlying NIFTY --start 2026-06-01 --end 2026-07-31
"""
from __future__ import annotations

import argparse
import datetime as dt


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _adapter(source: str):
    from .vendors import (SyntheticEODAdapter, NSEBhavcopyAdapter,
                          BSEBhavcopyAdapter)
    return {
        "synthetic": SyntheticEODAdapter,
        "nse": NSEBhavcopyAdapter,
        "bse": BSEBhavcopyAdapter,
    }[source]()


def cmd_ingest(args):
    from .ingestion import EODIngestionPipeline
    run = EODIngestionPipeline(_adapter(args.source)).ingest_range(
        _date(args.start), _date(args.end))
    print(f"run {run.run_id} source={run.source} rows={run.total_rows}")
    for d in run.days:
        flag = "QUARANTINED" if d.quarantined else "ok"
        print(f"  {d.trade_date} rows={d.rows} err={d.errors} warn={d.warnings} [{flag}]")
    if run.quarantined_days:
        print(f"quarantined: {run.quarantined_days}")
    print(f"manifest: {run.manifest_path}")


def cmd_setup_report(args):
    from .contracts import ContractSpecResolver
    from .marketcalendar import SEED_EXPIRY_RULES
    specs = ContractSpecResolver().unverified()
    print("=== Contract specs needing verification (verify=True) ===")
    for s in specs:
        print(f"  {s.underlying:9} {s.attribute:16} {s.value:5} "
              f"{s.valid_from}..{s.valid_to or 'current'}")
    print("\n=== Expiry rules needing verification ===")
    for r in SEED_EXPIRY_RULES:
        if r.verify:
            print(f"  {r.underlying:9} {r.valid_from}..{r.valid_to or 'current'}: {r.note}")


def cmd_expiries(args):
    from .marketcalendar import ExpiryResolver
    er = ExpiryResolver()
    rows = er.expiries_in_range(args.underlying, _date(args.start), _date(args.end))
    for x in rows:
        print(f"  {x['date']}  {x['type']}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="dataplatform")
    sub = p.add_subparsers(required=True)

    pi = sub.add_parser("ingest", help="ingest EOD F&O for a date range")
    pi.add_argument("--source", default="synthetic", choices=["synthetic", "nse", "bse"])
    pi.add_argument("--start", required=True)
    pi.add_argument("--end", required=True)
    pi.set_defaults(func=cmd_ingest)

    ps = sub.add_parser("setup-report", help="list reference data needing verification")
    ps.set_defaults(func=cmd_setup_report)

    pe = sub.add_parser("expiries", help="list expiries in a range")
    pe.add_argument("--underlying", required=True)
    pe.add_argument("--start", required=True)
    pe.add_argument("--end", required=True)
    pe.set_defaults(func=cmd_expiries)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
