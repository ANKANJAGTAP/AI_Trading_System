"""
Base class for bar/snapshot vendors (TrueData, Global Datafeeds, ...).

Subclasses provide a FieldMap and implement `_fetch_raw_chain` (the transport
that calls the vendor SDK/REST using the user's own credentials). The base
handles credential discovery and normalisation, so every vendor returns the
canonical EOD schema.

Credentials are read from environment variables ONLY — they are never passed
through chat or stored in the repo.
"""
from __future__ import annotations

import datetime as dt
import os

import pandas as pd

from .base import VendorAdapter
from .fieldmap import FieldMap, normalize
from ..config import EXCHANGE_OF


class BarVendorAdapter(VendorAdapter):
    id = "bar_vendor"
    fieldmap: FieldMap = None          # set by subclass
    required_env: tuple = ()           # env var names the transport needs

    def __init__(self, underlyings=("NIFTY", "FINNIFTY", "SENSEX")):
        self.underlyings = tuple(underlyings)

    # -- credentials / availability -------------------------------------
    def _creds(self) -> dict:
        return {k: os.environ.get(k) for k in self.required_env}

    def available(self) -> bool:
        return all(self._creds().values())

    # -- transport (subclass implements; needs live creds) --------------
    def _fetch_raw_chain(self, underlying: str, trade_date: dt.date) -> pd.DataFrame:
        raise NotImplementedError(
            f"{type(self).__name__} transport not wired. Implement _fetch_raw_chain "
            f"using the vendor SDK with env creds {self.required_env}."
        )

    # -- public API -----------------------------------------------------
    def fetch_eod_fno(self, trade_date: dt.date) -> pd.DataFrame:
        frames = []
        for u in self.underlyings:
            raw = self._fetch_raw_chain(u, trade_date)
            if raw is None or len(raw) == 0:
                continue
            frames.append(normalize(raw, self.fieldmap, u, EXCHANGE_OF.get(u, "NSE"),
                                    trade_date))
        if not frames:
            from .base import empty_canonical
            return empty_canonical()
        return pd.concat(frames, ignore_index=True)
