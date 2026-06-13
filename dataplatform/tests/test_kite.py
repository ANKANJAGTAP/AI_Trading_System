import datetime as dt

import pandas as pd

from dataplatform.vendors import KiteInstruments, KiteHistoricalAdapter
from dataplatform.vendors.base import CANONICAL_EOD_COLUMNS

_EXP = dt.date(2026, 6, 30)


def _dump():
    rows = [
        {"instrument_token": 1, "tradingsymbol": "NIFTY26JUNFUT", "name": "NIFTY",
         "expiry": _EXP, "strike": 0.0, "instrument_type": "FUT", "exchange": "NFO", "lot_size": 65},
        {"instrument_token": 2, "tradingsymbol": "NIFTY26JUN22000CE", "name": "NIFTY",
         "expiry": _EXP, "strike": 22000.0, "instrument_type": "CE", "exchange": "NFO", "lot_size": 65},
        {"instrument_token": 3, "tradingsymbol": "NIFTY26JUN22000PE", "name": "NIFTY",
         "expiry": _EXP, "strike": 22000.0, "instrument_type": "PE", "exchange": "NFO", "lot_size": 65},
        {"instrument_token": 4, "tradingsymbol": "NIFTY26JUN22100CE", "name": "NIFTY",
         "expiry": _EXP, "strike": 22100.0, "instrument_type": "CE", "exchange": "NFO", "lot_size": 65},
        {"instrument_token": 9, "tradingsymbol": "SENSEX26JUN80000CE", "name": "SENSEX",
         "expiry": _EXP, "strike": 80000.0, "instrument_type": "CE", "exchange": "BFO", "lot_size": 20},
    ]
    return KiteInstruments(pd.DataFrame(rows))


def test_instrument_lookups():
    ki = _dump()
    assert ki.expiries("NIFTY") == [_EXP]
    assert ki.resolve_token("NIFTY", _EXP, 22000, "CE") == 2
    assert ki.resolve_token("NIFTY", _EXP, opt_type="FUT") == 1
    assert ki.tradingsymbol_for("NIFTY", _EXP, 22000, "PE") == "NIFTY26JUN22000PE"
    assert ki.resolve_token("NIFTY", _EXP, 99999, "CE") is None      # missing strike
    assert len(ki.options_for("NIFTY", _EXP)) == 3                   # excludes SENSEX & FUT
    assert len(ki.futures_for("NIFTY", _EXP)) == 1


class _FakeKite(KiteHistoricalAdapter):
    """Override the candle transport so no kiteconnect/creds are needed offline."""
    def _bar(self, token, trade_date):
        return {"open": 100, "high": 110, "low": 95, "close": 105,
                "volume": 1000, "oi": 50000}


def test_fetch_eod_fno_builds_canonical_chain():
    ad = _FakeKite(api_key="k", access_token="t", instruments=_dump(), underlyings=("NIFTY",))
    df = ad.fetch_eod_fno(dt.date(2026, 6, 8))
    assert list(df.columns) == CANONICAL_EOD_COLUMNS
    assert (df["underlying"] == "NIFTY").all()
    assert (df["instrument"] == "OPT").sum() == 3
    assert (df["instrument"] == "FUT").sum() == 1
    assert (df["source"] == "kite").all()


def test_available_is_bool_without_sdk():
    # kiteconnect isn't installed in this env -> available() returns False, no raise
    ad = KiteHistoricalAdapter(api_key="k", access_token="t", instruments=_dump())
    assert ad.available() is False
