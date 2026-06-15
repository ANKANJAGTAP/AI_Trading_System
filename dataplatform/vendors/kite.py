"""
Zerodha Kite Connect adapter — historical candles + live + account.

With the paid Kite Connect plan (₹500/mo, live + historical bundled), Kite is a
first-class source for this platform:

  * Historical OHLCV+OI candles (1-min .. day) for index/futures/equity and the
    CURRENTLY ACTIVE option contracts  -> research / backtesting.
  * Live ticks / depth / OI via WebSocket                 -> forward capture.
  * Orders / positions / holdings / margins               -> execution & risk.

Honest limit: Kite's instruments dump lists only ACTIVE contracts, so this
backfills deep history of the underlying/futures and the *current* expiries'
option chains — not years of EXPIRED weeklies. For that, capture forward (store
each day's chain) or use a bulk historical vendor. The canonical schema is the
same either way, so nothing downstream changes.

SEBI 2026: API use needs static-IP whitelist, OAuth+2FA, Algo-ID tagging and OPS
limits — those live in the compliance layer; this module only reads/builds.
Credentials come from constructor args or env (KITE_API_KEY / KITE_ACCESS_TOKEN).
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass

import pandas as pd

from .bar_vendor import BarVendorAdapter
from .fieldmap import FieldMap

# we tag the raw chain with canonical-ish names, so the map is identity
KITE_FIELDMAP = FieldMap(
    open="open", high="high", low="low", close="close", volume="volume",
    strike="strike", opt_type="opt_type", expiry="expiry", oi="oi", source="kite",
)


def _to_date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return None
    if isinstance(v, dt.date) and not isinstance(v, dt.datetime):
        return v
    return pd.Timestamp(v).date()


@dataclass
class KiteInstruments:
    """Wrapper over Kite's instruments() dump with F&O lookups.

    Expected columns: instrument_token, tradingsymbol, name, expiry, strike,
    instrument_type ('CE'/'PE'/'FUT'/'EQ'), exchange, lot_size, segment.
    """
    df: pd.DataFrame

    @classmethod
    def from_kite(cls, kite, exchanges=("NFO", "BFO")) -> "KiteInstruments":
        rows = []
        for ex in exchanges:
            rows += kite.instruments(ex)
        return cls(pd.DataFrame(rows))

    @classmethod
    def from_csv(cls, path) -> "KiteInstruments":
        return cls(pd.read_csv(path))

    def expiries(self, underlying: str) -> list[dt.date]:
        d = self.df[self.df["name"] == underlying]
        out = {_to_date(e) for e in d["expiry"]}
        return sorted(x for x in out if x is not None)

    def _for(self, underlying: str, expiry: dt.date, types) -> pd.DataFrame:
        d = self.df[(self.df["name"] == underlying)
                    & (self.df["instrument_type"].isin(types))].copy()
        d = d[d["expiry"].map(_to_date) == expiry]
        return d

    def futures_for(self, underlying, expiry) -> pd.DataFrame:
        return self._for(underlying, expiry, ["FUT"])

    def options_for(self, underlying, expiry) -> pd.DataFrame:
        return self._for(underlying, expiry, ["CE", "PE"])

    def resolve_token(self, underlying, expiry, strike=None, opt_type="FUT"):
        row = self._match(underlying, expiry, strike, opt_type)
        return None if row is None else int(row["instrument_token"])

    def tradingsymbol_for(self, underlying, expiry, strike=None, opt_type="FUT"):
        row = self._match(underlying, expiry, strike, opt_type)
        return None if row is None else str(row["tradingsymbol"])

    def _match(self, underlying, expiry, strike, opt_type):
        d = self._for(underlying, _to_date(expiry), [opt_type])
        if opt_type in ("CE", "PE"):
            d = d[pd.to_numeric(d["strike"], errors="coerce") == float(strike)]
        return None if d.empty else d.iloc[0]


class KiteHistoricalAdapter(BarVendorAdapter):
    id = "kite"
    fieldmap = KITE_FIELDMAP
    required_env = ("KITE_API_KEY", "KITE_ACCESS_TOKEN")

    def __init__(self, api_key=None, access_token=None,
                 instruments: KiteInstruments | None = None,
                 underlyings=("NIFTY", "FINNIFTY", "SENSEX")):
        super().__init__(underlyings)
        self.api_key = api_key or os.environ.get("KITE_API_KEY")
        self.access_token = access_token or os.environ.get("KITE_ACCESS_TOKEN")
        self.instruments = instruments
        self._kite = None

    @classmethod
    def from_token_store(cls, instruments: KiteInstruments | None = None,
                         underlyings=("NIFTY", "FINNIFTY", "SENSEX")) -> "KiteHistoricalAdapter":
        """Build the adapter using today's stored access token (see dataplatform.kite_auth)."""
        from ..kite_auth import load_token
        token = load_token(
            os.environ.get("TOKEN_STORE_PATH", ".secrets/kite_token.json"),
            os.environ.get("TOKEN_ENCRYPTION_KEY") or None,
        )
        return cls(api_key=os.environ.get("KITE_API_KEY"), access_token=token,
                   instruments=instruments, underlyings=underlyings)

    # -- availability / client ------------------------------------------
    def available(self) -> bool:
        try:
            import kiteconnect  # noqa: F401
        except ImportError:
            return False
        return bool(self.api_key and self.access_token)   # instruments loaded separately

    def _client(self):
        if self._kite is None:
            from kiteconnect import KiteConnect
            self._kite = KiteConnect(api_key=self.api_key)
            self._kite.set_access_token(self.access_token)
        return self._kite

    def load_instruments(self, exchanges=("NFO", "BFO")) -> KiteInstruments:
        self.instruments = KiteInstruments.from_kite(self._client(), exchanges)
        return self.instruments

    # -- candle transport -----------------------------------------------
    def historical_candles(self, instrument_token: int, start: dt.datetime,
                           end: dt.datetime, interval: str = "minute") -> pd.DataFrame:
        """Candles for one token (ts, open, high, low, close, volume, oi)."""
        data = self._client().historical_data(instrument_token, start, end, interval, oi=True)
        df = pd.DataFrame(data)
        return df.rename(columns={"date": "ts"}) if not df.empty else df

    def _bar(self, token: int, trade_date: dt.date) -> dict | None:
        import time
        time.sleep(0.34)                      # stay under Kite's ~3 req/s historical limit
        try:
            data = self._client().historical_data(
                token,
                dt.datetime.combine(trade_date, dt.time(9, 0)),
                dt.datetime.combine(trade_date, dt.time(15, 40)),
                "day", oi=True,
            )
        except Exception:
            return None                       # skip a contract with no data / transient error
        if not data:
            return None
        b = data[-1]
        return {"open": b["open"], "high": b["high"], "low": b["low"],
                "close": b["close"], "volume": b.get("volume", 0), "oi": b.get("oi", 0)}

    # -- canonical chain (front expiry on/after trade_date) -------------
    def _fetch_raw_chain(self, underlying: str, trade_date: dt.date) -> pd.DataFrame:
        if self.instruments is None:
            raise RuntimeError("Call load_instruments() (or pass instruments=) first.")
        exps = [e for e in self.instruments.expiries(underlying) if e >= trade_date]
        if not exps:
            return pd.DataFrame()
        front = min(exps)
        rows = []
        for _, r in self.instruments.futures_for(underlying, front).iterrows():
            bar = self._bar(int(r["instrument_token"]), trade_date)
            if bar:
                rows.append({"strike": 0.0, "opt_type": "", "expiry": front, **bar})
        for _, r in self.instruments.options_for(underlying, front).iterrows():
            bar = self._bar(int(r["instrument_token"]), trade_date)
            if bar and bar.get("close") is not None:
                rows.append({"strike": float(r["strike"]), "opt_type": r["instrument_type"],
                             "expiry": front, **bar})
        return pd.DataFrame(rows)

    # -- account (read-only) --------------------------------------------
    def positions(self):
        return self._client().positions()

    def holdings(self):
        return self._client().holdings()

    def margins(self):
        return self._client().margins()

    def ticker(self):
        """Return a configured KiteTicker for live capture (you attach callbacks
        and run it). Store ticks via the ingestion layer to build history forward."""
        from kiteconnect import KiteTicker
        return KiteTicker(self.api_key, self.access_token)


# Back-compat alias
KiteAdapter = KiteHistoricalAdapter
