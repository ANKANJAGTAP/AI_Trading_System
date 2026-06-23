import datetime as dt

from dataplatform.vendors import DhanChainAdapter, gdfl_symbol
from dataplatform.vendors.base import CANONICAL_EOD_COLUMNS


def test_gdfl_symbol_format():
    s = gdfl_symbol("SENSEX", dt.date(2026, 6, 25), 80000, "PE")
    assert s.startswith("SENSEX") and "80000" in s and s.endswith("PE")
    assert gdfl_symbol("NIFTY", dt.date(2026, 6, 25)).endswith("FUT")


def test_dhan_chain_available_requires_env(monkeypatch):
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    assert DhanChainAdapter().available() is False
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "jwt")
    monkeypatch.setenv("DHAN_CLIENT_ID", "123")
    assert DhanChainAdapter().available() is True


class _FakeDhanChain(DhanChainAdapter):
    """Override the transport touch-points with a deterministic chain (offline)."""

    def expiry_list(self, underlying):
        return [dt.date(2026, 6, 25)]

    def chain_snapshot(self, underlying, expiry):
        leg_ce = {"last_price": 120, "oi": 1000, "volume": 50, "previous_oi": 900,
                  "implied_volatility": 12.5,
                  "greeks": {"delta": 0.55, "theta": -4.2, "gamma": 0.0008, "vega": 7.1},
                  "top_bid_price": 119.5, "top_ask_price": 120.5,
                  "top_bid_quantity": 75, "top_ask_quantity": 80}
        leg_pe = {"last_price": 95, "oi": 1500, "volume": 60, "previous_oi": 1400,
                  "implied_volatility": 13.0,
                  "greeks": {"delta": -0.45, "theta": -3.9, "gamma": 0.0008, "vega": 7.0},
                  "top_bid_price": 94.5, "top_ask_price": 95.5,
                  "top_bid_quantity": 50, "top_ask_quantity": 50}
        return {"data": {"last_price": 22000, "oc": {
            "21950.000000": {"ce": leg_ce, "pe": leg_pe},
            "22000.000000": {"ce": {"last_price": 0, "oi": 0}, "pe": {"last_price": 80, "oi": 800}},
        }}}


def test_dhan_chain_fetch_eod_fno_via_fake_transport():
    ad = _FakeDhanChain(underlyings=("NIFTY",), n_expiries=1)
    df = ad.fetch_eod_fno(dt.date(2026, 6, 8))
    assert list(df.columns) == CANONICAL_EOD_COLUMNS
    assert (df["underlying"] == "NIFTY").all()
    assert (df["instrument"] == "OPT").all()          # an option chain is options-only
    assert set(df["opt_type"]) == {"CE", "PE"}
    assert (df["source"] == "dhan").all()
    assert len(df) == 3                               # the dead 22000-CE (no ltp/oi) is skipped


def test_dhan_chain_rich_rows_carry_greeks():
    ad = _FakeDhanChain(underlyings=("NIFTY",), n_expiries=1)
    rows = ad.fetch_chain_rows("NIFTY", dt.date(2026, 6, 25), asof=dt.date(2026, 6, 8))
    ce = next(r for r in rows if r["opt_type"] == "CE" and r["strike"] == 21950.0)
    assert ce["delta"] == 0.55 and ce["vega"] == 7.1 and ce["iv"] == 12.5
    assert ce["bid"] == 119.5 and ce["ask"] == 120.5 and ce["oi"] == 1000
    assert ce["underlying_ltp"] == 22000.0
