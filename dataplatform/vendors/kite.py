"""
Zerodha Kite Connect adapter.

Kite is your LIVE feed + execution path and a source of RECENT historical
candles — it is NOT a deep options-chain EOD source (instrument tokens churn as
weekly options expire, and history depth/rate limits are restrictive). So:

  * deep EOD history  -> NSE/BSE bhavcopy adapters + a paid vendor (TrueData/GDFL)
  * recent candles    -> this adapter's `historical_candles`
  * live ticks/orders -> Kite WebSocket + order API (engine layer, not here)

SEBI 2026 (mandatory 1 Apr 2026): API use requires static-IP whitelisting,
OAuth + 2FA, auto session logout before pre-open, Algo-ID tagging on orders, and
OPS limits. Those controls live in the engine/compliance layer; this adapter
only reads data.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from .base import VendorAdapter


class KiteAdapter(VendorAdapter):
    id = "kite"

    def __init__(self, api_key: str | None = None, access_token: str | None = None):
        self.api_key = api_key
        self.access_token = access_token
        self._kite = None

    def available(self) -> bool:
        try:
            import kiteconnect  # noqa: F401
        except ImportError:
            return False
        return bool(self.api_key and self.access_token)

    def _client(self):
        if self._kite is None:
            from kiteconnect import KiteConnect
            self._kite = KiteConnect(api_key=self.api_key)
            self._kite.set_access_token(self.access_token)
        return self._kite

    def historical_candles(
        self,
        instrument_token: int,
        start: dt.datetime,
        end: dt.datetime,
        interval: str = "minute",
    ) -> pd.DataFrame:
        """Recent OHLC candles for one instrument token (subject to Kite limits).

        Returns columns: ts, open, high, low, close, volume, oi.
        """
        kite = self._client()
        data = kite.historical_data(
            instrument_token, start, end, interval, oi=True
        )
        df = pd.DataFrame(data)
        if not df.empty:
            df = df.rename(columns={"date": "ts"})
        return df

    def fetch_eod_fno(self, trade_date: dt.date) -> pd.DataFrame:
        raise NotImplementedError(
            "Kite is not a full-chain EOD bhavcopy source. Use NSE/BSE bhavcopy "
            "adapters for EOD history and a paid vendor for deep 1-min options "
            "history; use Kite for recent candles (historical_candles) and live."
        )
