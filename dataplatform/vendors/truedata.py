"""
TrueData adapter (paid 1-min + EOD F&O history).

Transport uses the official `truedata` Python SDK with credentials from the
environment (TRUEDATA_USERNAME / TRUEDATA_PASSWORD) — never from chat or the
repo. The adapter:
  1. resolves expiries via the Pillar-1 ExpiryResolver,
  2. finds ATM from the front-future close,
  3. builds the option universe (strike band) and fetches each EOD bar,
  4. tags rows with strike/opt_type/expiry and normalises to the canonical schema.

⚠️ SYMBOLOGY: TrueData's exact option symbol format depends on your subscription's
symbol master. The default `truedata_symbol` pattern is a documented best guess
flagged verify — confirm it against your TrueData symbol list and adjust the
`symbol_format` callable if needed.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from .bar_vendor import BarVendorAdapter
from .fieldmap import FieldMap
from ..config import EXCHANGE_OF
from ..contracts import ContractSpecResolver
from ..marketcalendar import ExpiryResolver

# We assemble the raw chain with canonical-ish column names, so the map is identity.
TRUEDATA_FIELDMAP = FieldMap(
    open="open", high="high", low="low", close="close", volume="volume",
    strike="strike", opt_type="opt_type", expiry="expiry", oi="oi",
    source="truedata",
)


def truedata_symbol(underlying: str, expiry: dt.date,
                    strike: float | None = None, opt_type: str | None = None) -> str:
    """Default TrueData symbol pattern — VERIFY against your symbol master.

    Options: ``NIFTY24JUL18000CE``   Futures: ``NIFTY24JULFUT``
    """
    base = f"{underlying}{expiry:%d%b%y}".upper().replace(" ", "")
    if opt_type in ("CE", "PE") and strike is not None:
        return f"{base}{int(round(strike))}{opt_type}"
    return f"{base}FUT"


class TrueDataAdapter(BarVendorAdapter):
    id = "truedata"
    fieldmap = TRUEDATA_FIELDMAP
    required_env = ("TRUEDATA_USERNAME", "TRUEDATA_PASSWORD")

    def __init__(self, underlyings=("NIFTY", "FINNIFTY", "SENSEX"),
                 n_strikes: int = 15, step: float = 50.0,
                 symbol_format=truedata_symbol):
        super().__init__(underlyings)
        self.n_strikes = n_strikes
        self.step = step
        self.symbol_format = symbol_format
        self.expiry = ExpiryResolver()
        self.specs = ContractSpecResolver()
        self._client = None

    # -- transport (single SDK touch-point) -----------------------------
    def _connect(self):
        if self._client is None:
            from truedata import TD_hist          # lazy import; needs the SDK
            creds = self._creds()
            self._client = TD_hist(creds["TRUEDATA_USERNAME"], creds["TRUEDATA_PASSWORD"])
        return self._client

    def _eod_bar(self, symbol: str, trade_date: dt.date) -> dict | None:
        """Return one EOD OHLCV+OI bar for `symbol` on `trade_date`, or None."""
        td = self._connect()
        bars = td.get_historic_data(
            symbol,
            start_time=dt.datetime.combine(trade_date, dt.time(9, 0)),
            end_time=dt.datetime.combine(trade_date, dt.time(15, 40)),
            bar_size="EOD",
        )
        if not bars:
            return None
        b = bars[-1]
        g = (lambda k: b.get(k) if isinstance(b, dict) else getattr(b, k, None))
        return {"open": g("open"), "high": g("high"), "low": g("low"),
                "close": g("close"), "volume": g("volume") or 0, "oi": g("oi") or 0}

    # -- universe + assembly --------------------------------------------
    def _expiries(self, underlying: str, asof: dt.date) -> list[dt.date]:
        out = []
        w = self.expiry.next_weekly_expiry(underlying, asof)
        if w:
            out.append(w)
        out.append(self.expiry.current_monthly_expiry(underlying, asof))
        return sorted(set(out))

    def _fetch_raw_chain(self, underlying: str, trade_date: dt.date) -> pd.DataFrame:
        rows = []
        for expiry in self._expiries(underlying, trade_date):
            # 1) future bar -> ATM
            fut = self._eod_bar(self.symbol_format(underlying, expiry), trade_date)
            if fut and fut.get("close"):
                rows.append({"strike": 0.0, "opt_type": "", "expiry": expiry, **fut})
                atm = round(fut["close"] / self.step) * self.step
            else:
                continue
            # 2) option band around ATM
            for k in range(-self.n_strikes, self.n_strikes + 1):
                strike = atm + k * self.step
                if strike <= 0:
                    continue
                for opt in ("CE", "PE"):
                    bar = self._eod_bar(self.symbol_format(underlying, expiry, strike, opt), trade_date)
                    if bar and bar.get("close") is not None:
                        rows.append({"strike": float(strike), "opt_type": opt,
                                     "expiry": expiry, **bar})
        return pd.DataFrame(rows)
