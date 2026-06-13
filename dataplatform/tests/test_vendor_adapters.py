import datetime as dt

from dataplatform.vendors import TrueDataAdapter, truedata_symbol, gdfl_symbol
from dataplatform.vendors.base import CANONICAL_EOD_COLUMNS


def test_symbol_formats():
    s = truedata_symbol("NIFTY", dt.date(2026, 6, 25), 22000, "CE")
    assert s.startswith("NIFTY") and "22000" in s and s.endswith("CE")
    assert truedata_symbol("NIFTY", dt.date(2026, 6, 25)).endswith("FUT")
    assert gdfl_symbol("SENSEX", dt.date(2026, 6, 25), 80000, "PE").endswith("PE")


def test_available_requires_env(monkeypatch):
    monkeypatch.delenv("TRUEDATA_USERNAME", raising=False)
    monkeypatch.delenv("TRUEDATA_PASSWORD", raising=False)
    assert TrueDataAdapter().available() is False
    monkeypatch.setenv("TRUEDATA_USERNAME", "u")
    monkeypatch.setenv("TRUEDATA_PASSWORD", "p")
    assert TrueDataAdapter().available() is True


class _FakeTrueData(TrueDataAdapter):
    """Override the single SDK touch-point with deterministic bars (offline)."""
    def _eod_bar(self, symbol, trade_date):
        if symbol.endswith("FUT"):
            return {"open": 22000, "high": 22100, "low": 21900, "close": 22000,
                    "volume": 100000, "oi": 500000}
        return {"open": 100, "high": 110, "low": 95, "close": 105,
                "volume": 2000, "oi": 40000}


def test_fetch_eod_fno_via_fake_transport():
    ad = _FakeTrueData(underlyings=("NIFTY",), n_strikes=3, step=50.0)
    df = ad.fetch_eod_fno(dt.date(2026, 6, 8))
    assert list(df.columns) == CANONICAL_EOD_COLUMNS
    assert (df["underlying"] == "NIFTY").all()
    assert set(df["instrument"]).issubset({"FUT", "OPT"})
    assert (df["instrument"] == "OPT").sum() > 0
    assert (df["instrument"] == "FUT").sum() > 0
    assert (df["source"] == "truedata").all()
