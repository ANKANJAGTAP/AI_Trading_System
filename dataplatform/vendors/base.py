"""
Pluggable vendor-adapter interface.

Every data source (free bhavcopy, TrueData, Global Datafeeds, Kite, ...) is a
subclass that returns data in ONE canonical normalised schema, so the rest of
the platform never cares where bytes came from. This is what keeps you
vendor-independent.
"""
from __future__ import annotations

import abc
import datetime as dt

import pandas as pd

# Canonical normalised EOD F&O schema. Every adapter MUST return these columns.
CANONICAL_EOD_COLUMNS = [
    "trade_date",   # date
    "underlying",   # 'NIFTY' | 'FINNIFTY' | 'SENSEX'
    "exchange",     # 'NSE' | 'BSE'
    "instrument",   # 'FUT' | 'OPT'
    "opt_type",     # 'CE' | 'PE' | '' (futures)
    "expiry",       # date
    "strike",       # float (0 for futures)
    "open", "high", "low", "close", "settle",
    "volume",       # contracts traded
    "oi",           # open interest (contracts)
    "oi_change",    # change in OI
    "source",       # adapter id, for lineage
]


def empty_canonical() -> pd.DataFrame:
    return pd.DataFrame(columns=CANONICAL_EOD_COLUMNS)


def validate_canonical(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure the frame has exactly the canonical columns (order-normalised)."""
    missing = set(CANONICAL_EOD_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"adapter output missing columns: {sorted(missing)}")
    return df[CANONICAL_EOD_COLUMNS].copy()


class VendorAdapter(abc.ABC):
    """Base class for all data vendors."""

    #: short identifier written into the `source` column for lineage
    id: str = "base"

    @abc.abstractmethod
    def fetch_eod_fno(self, trade_date: dt.date) -> pd.DataFrame:
        """Return ALL F&O EOD rows for `trade_date` in the canonical schema.

        Implementations should restrict to the Phase-A underlyings or return
        everything and let the pipeline filter — both are fine as long as the
        output is canonical.
        """
        raise NotImplementedError

    def available(self) -> bool:
        """Cheap check that this adapter can run (creds/network present)."""
        return True
