"""DhanHQ option-chain normalisation (pure — no network/DB)."""
import datetime as dt

from dataplatform.vendors.dhan_chain import (chain_rows_to_records,
                                             parse_expiry_list, parse_option_chain)


def _chain():
    return {"data": {"last_price": 22011.5, "oc": {
        "21900.000000": {
            "ce": {"last_price": 150.0, "oi": 2000, "volume": 100, "previous_oi": 1800,
                   "implied_volatility": 11.8,
                   "greeks": {"delta": 0.62, "theta": -5.1, "gamma": 0.0007, "vega": 6.5},
                   "top_bid_price": 149.5, "top_ask_price": 150.5,
                   "top_bid_quantity": 75, "top_ask_quantity": 100},
            "pe": {"last_price": 70.0, "oi": 2500, "volume": 120, "previous_oi": 2400,
                   "implied_volatility": 12.4,
                   "greeks": {"delta": -0.38, "theta": -4.4, "gamma": 0.0007, "vega": 6.4},
                   "top_bid_price": 69.5, "top_ask_price": 70.5,
                   "top_bid_quantity": 50, "top_ask_quantity": 60},
        },
        "21950.000000": {
            "ce": {"last_price": None, "oi": 0},          # dead leg -> skipped
            "pe": {"last_price": 80.0, "oi": 900, "greeks": {}},
        },
    }}}


def test_parse_option_chain_extracts_legs_and_greeks():
    rows = parse_option_chain(_chain(), expiry=dt.date(2026, 6, 25),
                              asof=dt.date(2026, 6, 23), underlying="NIFTY")
    assert len(rows) == 3                                 # 21900 CE/PE + 21950 PE
    ce = next(r for r in rows if r["strike"] == 21900.0 and r["opt_type"] == "CE")
    assert ce["delta"] == 0.62 and ce["iv"] == 11.8 and ce["vega"] == 6.5
    assert ce["bid"] == 149.5 and ce["ask"] == 150.5
    assert ce["oi"] == 2000 and ce["volume"] == 100 and ce["previous_oi"] == 1800
    assert ce["underlying_ltp"] == 22011.5 and ce["underlying"] == "NIFTY"
    assert ce["expiry"] == dt.date(2026, 6, 25) and ce["asof"] == dt.date(2026, 6, 23)
    assert [(r["strike"], r["opt_type"]) for r in rows] == [
        (21900.0, "CE"), (21900.0, "PE"), (21950.0, "PE")]   # sorted (strike, type)


def test_parse_option_chain_missing_greeks_default_none():
    rows = parse_option_chain(_chain(), expiry="2026-06-25", asof="2026-06-23")
    pe = next(r for r in rows if r["strike"] == 21950.0)
    assert pe["delta"] is None and pe["iv"] is None       # greeks {} / no iv -> None
    assert pe["oi"] == 900 and pe["close"] == 80.0


def test_parse_option_chain_empty():
    assert parse_option_chain({}, expiry=dt.date(2026, 6, 25)) == []
    assert parse_option_chain(None, expiry=dt.date(2026, 6, 25)) == []
    assert parse_option_chain({"data": {"oc": {}}}, expiry=dt.date(2026, 6, 25)) == []


def test_parse_expiry_list():
    out = parse_expiry_list({"data": ["2026-06-25", "2026-07-02", "2026-06-25", "garbage"]})
    assert out == [dt.date(2026, 6, 25), dt.date(2026, 7, 2)]   # deduped, sorted, junk dropped
    assert parse_expiry_list({}) == [] and parse_expiry_list(None) == []


def test_chain_rows_to_records_serialises_dates_and_trims():
    rows = parse_option_chain(_chain(), expiry=dt.date(2026, 6, 25),
                              asof=dt.date(2026, 6, 23), underlying="NIFTY")
    recs = chain_rows_to_records(rows)
    assert recs[0]["expiry"] == "2026-06-25" and recs[0]["asof"] == "2026-06-23"
    assert {"delta", "iv", "oi", "bid", "ask", "strike", "opt_type"}.issubset(recs[0])
    assert "open" not in recs[0] and "high" not in recs[0]      # scratch OHLC trimmed
