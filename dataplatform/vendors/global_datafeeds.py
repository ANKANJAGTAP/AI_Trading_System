"""
Global Datafeeds (GDFL) adapter — authorised NSE/BSE/MCX data vendor.

Transport uses GDFL's Historical Data REST API with an API key from the
environment (GDFL_API_KEY, optional GDFL_ENDPOINT). Structure mirrors the
other bar-vendor adapters; only the per-symbol fetch and symbology differ.

⚠️ Confirm the endpoint, response fields and symbology against your GDFL plan;
the defaults are documented best guesses flagged verify.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse
import urllib.request

import pandas as pd

from .bar_vendor import BarVendorAdapter
from .fieldmap import FieldMap
from ..contracts import ContractSpecResolver
from ..marketcalendar import ExpiryResolver

GDFL_FIELDMAP = FieldMap(
    open="open", high="high", low="low", close="close", volume="volume",
    strike="strike", opt_type="opt_type", expiry="expiry", oi="oi",
    source="global_datafeeds",
)

_DEFAULT_ENDPOINT = "https://history.globaldatafeeds.in/api/Data/HistoryData"


def gdfl_symbol(underlying: str, expiry: dt.date,
                strike: float | None = None, opt_type: str | None = None) -> str:
    """Default GDFL symbol pattern — VERIFY against your GDFL symbol master.

    Options: ``NIFTY24JUL18000CE``   Futures: ``NIFTY24JULFUT``
    """
    base = f"{underlying}{expiry:%d%b%y}".upper().replace(" ", "")
    if opt_type in ("CE", "PE") and strike is not None:
        return f"{base}{int(round(strike))}{opt_type}"
    return f"{base}FUT"


class GlobalDatafeedsAdapter(BarVendorAdapter):
    id = "global_datafeeds"
    fieldmap = GDFL_FIELDMAP
    required_env = ("GDFL_API_KEY",)

    def __init__(self, underlyings=("NIFTY", "FINNIFTY", "SENSEX"),
                 n_strikes: int = 15, step: float = 50.0, symbol_format=gdfl_symbol):
        super().__init__(underlyings)
        self.n_strikes = n_strikes
        self.step = step
        self.symbol_format = symbol_format
        self.expiry = ExpiryResolver()
        self.specs = ContractSpecResolver()
        self.endpoint = os.environ.get("GDFL_ENDPOINT", _DEFAULT_ENDPOINT)

    def _eod_bar(self, symbol: str, exchange: str, trade_date: dt.date) -> dict | None:
        params = {
            "accesskey": self._creds()["GDFL_API_KEY"],
            "exchange": exchange, "instrumentidentifier": symbol,
            "periodicity": "DAY",
            "from": int(dt.datetime.combine(trade_date, dt.time(9, 0)).timestamp()),
            "to": int(dt.datetime.combine(trade_date, dt.time(15, 40)).timestamp()),
        }
        url = f"{self.endpoint}?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        recs = data.get("data", data) if isinstance(data, dict) else data
        if not recs:
            return None
        b = recs[-1]
        return {"open": b.get("Open"), "high": b.get("High"), "low": b.get("Low"),
                "close": b.get("Close"), "volume": b.get("Volume") or 0,
                "oi": b.get("OpenInterest") or 0}

    def _expiries(self, underlying, asof):
        out = []
        w = self.expiry.next_weekly_expiry(underlying, asof)
        if w:
            out.append(w)
        out.append(self.expiry.current_monthly_expiry(underlying, asof))
        return sorted(set(out))

    def _fetch_raw_chain(self, underlying: str, trade_date: dt.date) -> pd.DataFrame:
        from ..config import EXCHANGE_OF
        exch = EXCHANGE_OF.get(underlying, "NSE")
        rows = []
        for expiry in self._expiries(underlying, trade_date):
            fut = self._eod_bar(self.symbol_format(underlying, expiry), exch, trade_date)
            if not (fut and fut.get("close")):
                continue
            rows.append({"strike": 0.0, "opt_type": "", "expiry": expiry, **fut})
            atm = round(fut["close"] / self.step) * self.step
            for k in range(-self.n_strikes, self.n_strikes + 1):
                strike = atm + k * self.step
                if strike <= 0:
                    continue
                for opt in ("CE", "PE"):
                    bar = self._eod_bar(self.symbol_format(underlying, expiry, strike, opt),
                                        exch, trade_date)
                    if bar and bar.get("close") is not None:
                        rows.append({"strike": float(strike), "opt_type": opt,
                                     "expiry": expiry, **bar})
        return pd.DataFrame(rows)
