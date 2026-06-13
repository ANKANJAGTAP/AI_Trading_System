"""
Synthetic EOD F&O adapter — deterministic, offline, no network.

Generates a plausible futures + option-chain bhavcopy for a given date using the
real expiry/spec resolvers. Its purpose is to let the WHOLE pipeline (ingest ->
quality -> lake/DB) be tested end-to-end with zero external dependencies, and to
serve as a reference for what a normalised adapter output looks like.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math

import pandas as pd

from .base import VendorAdapter, validate_canonical
from ..contracts import ContractSpecResolver
from ..marketcalendar import ExpiryResolver

# rough synthetic spot levels per underlying (index points)
_BASE_SPOT = {"NIFTY": 22000.0, "FINNIFTY": 21000.0, "SENSEX": 72000.0}
_STEP = {"NIFTY": 50.0, "FINNIFTY": 50.0, "SENSEX": 100.0}  # strike spacing


def _seeded_unit(*parts) -> float:
    """Deterministic pseudo-random in [0,1) from the given parts."""
    h = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


class SyntheticEODAdapter(VendorAdapter):
    id = "synthetic"

    def __init__(self, underlyings=("NIFTY", "FINNIFTY", "SENSEX"),
                 strikes_each_side: int = 10):
        self.underlyings = tuple(underlyings)
        self.n = strikes_each_side
        self.specs = ContractSpecResolver()
        self.expiry = ExpiryResolver()

    def _spot(self, underlying: str, d: dt.date) -> float:
        base = _BASE_SPOT[underlying]
        drift = (_seeded_unit(underlying, d.toordinal()) - 0.5) * 0.04  # +/-2%
        return round(base * (1 + drift), 2)

    def fetch_eod_fno(self, trade_date: dt.date) -> pd.DataFrame:
        from ..config import EXCHANGE_OF

        rows = []
        for u in self.underlyings:
            exch = EXCHANGE_OF[u]
            spot = self._spot(u, trade_date)
            step = _STEP[u]
            atm = round(spot / step) * step

            # expiries to include: current monthly + (nearest weekly if available)
            expiries = {self.expiry.current_monthly_expiry(u, trade_date)}
            w = self.expiry.next_weekly_expiry(u, trade_date)
            if w is not None:
                expiries.add(w)

            for expiry in sorted(expiries):
                # ---- futures ----
                fut_close = round(spot * (1 + 0.0008), 2)  # tiny basis
                rows.append(self._row(u, exch, "FUT", "", expiry, 0.0,
                                      fut_close, trade_date, base_oi=200000))

                # ---- option chain ----
                dte = max(self.expiry.days_to_expiry(u, trade_date, expiry), 1)
                for k in range(-self.n, self.n + 1):
                    strike = atm + k * step
                    if strike <= 0:
                        continue
                    for opt in ("CE", "PE"):
                        price = self._opt_price(spot, strike, dte, opt)
                        rows.append(self._row(u, exch, "OPT", opt, expiry,
                                              strike, price, trade_date,
                                              base_oi=50000))

        df = pd.DataFrame(rows)
        return validate_canonical(df)

    # ------------------------------------------------------------------ #
    def _opt_price(self, spot, strike, dte, opt) -> float:
        """Crude but monotone option value: intrinsic + simple time value."""
        intrinsic = max(spot - strike, 0) if opt == "CE" else max(strike - spot, 0)
        time_val = spot * 0.004 * math.sqrt(dte) * math.exp(
            -((spot - strike) / (spot * 0.05)) ** 2)
        return round(max(intrinsic + time_val, 0.05), 2)

    def _row(self, u, exch, instrument, opt, expiry, strike, close, d,
             base_oi) -> dict:
        jit = 1 + (_seeded_unit(u, instrument, opt, strike, d.toordinal()) - 0.5) * 0.02
        c = round(close * jit, 2)
        o = round(c * (1 + (_seeded_unit("o", u, strike, d) - 0.5) * 0.02), 2)
        hi = round(max(o, c) * 1.01, 2)
        lo = round(min(o, c) * 0.99, 2)
        vol = int(1000 + _seeded_unit("v", u, strike, opt, d) * 50000)
        oi = int(base_oi * (0.5 + _seeded_unit("oi", u, strike, opt, d)))
        oi_chg = int((_seeded_unit("oic", u, strike, opt, d) - 0.5) * oi * 0.2)
        return {
            "trade_date": d, "underlying": u, "exchange": exch,
            "instrument": instrument, "opt_type": opt, "expiry": expiry,
            "strike": float(strike), "open": o, "high": hi, "low": lo,
            "close": c, "settle": c, "volume": vol, "oi": oi,
            "oi_change": oi_chg, "source": self.id,
        }
