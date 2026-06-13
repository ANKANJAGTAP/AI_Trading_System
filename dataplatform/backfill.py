"""
Historical backfill orchestration.

`build_option_universe` uses the Pillar-1 ExpiryResolver to enumerate the
expiries (front weekly + front monthly) and a strike band around ATM — so the
universe automatically respects the real expiry rules (e.g. FinNifty monthly-only).
`run_backfill` drives any VendorAdapter through the EOD ingestion pipeline, so it
works identically for the synthetic adapter (tested here) and the paid vendors
(in your environment with credentials).
"""
from __future__ import annotations

import datetime as dt

from .marketcalendar import ExpiryResolver
from .ingestion import EODIngestionPipeline


def build_option_universe(underlying: str, asof: dt.date, atm_spot: float,
                          n_strikes: int = 15, step: float = 50.0,
                          resolver: ExpiryResolver | None = None) -> list[dict]:
    """Specs (expiry, strike, opt_type) to fetch for one underlying as-of a date."""
    resolver = resolver or ExpiryResolver()
    expiries = []
    w = resolver.next_weekly_expiry(underlying, asof)
    if w:
        expiries.append(w)
    expiries.append(resolver.current_monthly_expiry(underlying, asof))
    expiries = sorted(set(expiries))

    atm = round(atm_spot / step) * step
    specs = []
    for e in expiries:
        specs.append({"expiry": e, "strike": 0.0, "opt_type": ""})    # future
        for k in range(-n_strikes, n_strikes + 1):
            strike = atm + k * step
            if strike <= 0:
                continue
            for opt in ("CE", "PE"):
                specs.append({"expiry": e, "strike": float(strike), "opt_type": opt})
    return specs


def run_backfill(adapter, start: dt.date, end: dt.date, **pipeline_kwargs):
    """Ingest EOD F&O for [start, end] from `adapter` (any VendorAdapter)."""
    pipe = EODIngestionPipeline(adapter, **pipeline_kwargs)
    return pipe.ingest_range(start, end)
