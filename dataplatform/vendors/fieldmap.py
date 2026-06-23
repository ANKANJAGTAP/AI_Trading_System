"""
Vendor field-map normaliser.

Every paid vendor (Dhan option chain, Global Datafeeds, ...) returns option/future bars
with its OWN column names and codes. A FieldMap declares how that vendor's
columns map to the canonical EOD schema, and `normalize()` does the conversion.
So onboarding a new vendor is: define a FieldMap (data), not write new code.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .base import validate_canonical


@dataclass
class FieldMap:
    """Mapping from canonical fields -> this vendor's column names.

    A value of None means "not provided by the vendor" and a sensible default is
    derived (e.g. settle<-close, oi<-0, instrument inferred from opt_type).
    """
    open: str
    high: str
    low: str
    close: str
    volume: str
    strike: str | None = None
    opt_type: str | None = None
    instrument: str | None = None      # vendor column giving FUT/OPT (else inferred)
    expiry: str | None = None
    settle: str | None = None
    oi: str | None = None
    oi_change: str | None = None
    source: str = "vendor"
    # code translation tables
    opt_type_map: dict = field(default_factory=lambda: {"CE": "CE", "PE": "PE",
                                                         "CALL": "CE", "PUT": "PE", "XX": ""})
    instrument_map: dict = field(default_factory=lambda: {"OPT": "OPT", "FUT": "FUT"})


def _to_date(v) -> dt.date:
    if isinstance(v, dt.date) and not isinstance(v, dt.datetime):
        return v
    return pd.Timestamp(v).date()


def normalize(raw: pd.DataFrame, fmap: FieldMap, underlying: str, exchange: str,
              trade_date) -> pd.DataFrame:
    """Convert one vendor chain snapshot (per-row option/future records, for a
    single underlying + trade_date) into the canonical EOD schema."""
    out = pd.DataFrame(index=raw.index)
    out["trade_date"] = _to_date(trade_date)
    out["underlying"] = underlying
    out["exchange"] = exchange

    # option type
    if fmap.opt_type and fmap.opt_type in raw:
        out["opt_type"] = raw[fmap.opt_type].map(
            lambda v: fmap.opt_type_map.get(str(v).strip().upper(),
                                            str(v).strip().upper() if str(v).strip().upper() in ("CE", "PE") else "")
        )
    else:
        out["opt_type"] = ""

    # instrument (explicit column, else infer from opt_type)
    if fmap.instrument and fmap.instrument in raw:
        out["instrument"] = raw[fmap.instrument].map(
            lambda v: fmap.instrument_map.get(str(v).strip().upper(), "OPT"))
    else:
        out["instrument"] = np.where(out["opt_type"].isin(["CE", "PE"]), "OPT", "FUT")

    out["expiry"] = (raw[fmap.expiry].map(_to_date) if fmap.expiry and fmap.expiry in raw
                     else _to_date(trade_date))
    out["strike"] = (pd.to_numeric(raw[fmap.strike], errors="coerce").fillna(0.0)
                     if fmap.strike and fmap.strike in raw else 0.0)

    for f in ("open", "high", "low", "close"):
        out[f] = pd.to_numeric(raw[getattr(fmap, f)], errors="coerce")
    out["settle"] = (pd.to_numeric(raw[fmap.settle], errors="coerce")
                     if fmap.settle and fmap.settle in raw else out["close"])
    out["volume"] = (pd.to_numeric(raw[fmap.volume], errors="coerce").fillna(0).astype("int64")
                     if fmap.volume in raw else 0)
    out["oi"] = (pd.to_numeric(raw[fmap.oi], errors="coerce").fillna(0).astype("int64")
                 if fmap.oi and fmap.oi in raw else 0)
    out["oi_change"] = (pd.to_numeric(raw[fmap.oi_change], errors="coerce").fillna(0).astype("int64")
                        if fmap.oi_change and fmap.oi_change in raw else 0)
    out["source"] = fmap.source
    return validate_canonical(out)
