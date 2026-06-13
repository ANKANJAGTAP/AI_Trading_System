import datetime as dt

import pandas as pd

from dataplatform.vendors import FieldMap, normalize
from dataplatform.vendors.base import CANONICAL_EOD_COLUMNS

FMAP = FieldMap(open="open", high="high", low="low", close="close", volume="volume",
                strike="strike", opt_type="opt_type", expiry="expiry", oi="oi",
                source="vendorX")


def _raw():
    return pd.DataFrame([
        {"strike": 0.0, "opt_type": "", "expiry": dt.date(2026, 6, 25),
         "open": 100, "high": 105, "low": 99, "close": 102, "volume": 1000, "oi": 50000},
        {"strike": 22000.0, "opt_type": "CE", "expiry": dt.date(2026, 6, 25),
         "open": 150, "high": 160, "low": 140, "close": 155, "volume": 500, "oi": 30000},
    ])


def test_normalize_schema_and_instrument_inference():
    out = normalize(_raw(), FMAP, "NIFTY", "NSE", dt.date(2026, 6, 8))
    assert list(out.columns) == CANONICAL_EOD_COLUMNS
    assert (out["underlying"] == "NIFTY").all() and (out["exchange"] == "NSE").all()
    fut = out[out["instrument"] == "FUT"].iloc[0]
    assert fut["opt_type"] == ""                      # inferred FUT from blank opt_type
    opt = out[out["instrument"] == "OPT"].iloc[0]
    assert opt["opt_type"] == "CE" and opt["strike"] == 22000.0
    assert (out["source"] == "vendorX").all()


def test_settle_defaults_to_close_and_oichange_zero():
    out = normalize(_raw(), FMAP, "NIFTY", "NSE", dt.date(2026, 6, 8))
    assert (out["settle"] == out["close"]).all()
    assert (out["oi_change"] == 0).all()


def test_opt_code_translation():
    raw = pd.DataFrame([{"strike": 100, "opt_type": "CALL", "expiry": dt.date(2026, 6, 25),
                         "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "oi": 1}])
    out = normalize(raw, FMAP, "NIFTY", "NSE", dt.date(2026, 6, 8))
    assert out["opt_type"].iloc[0] == "CE"            # CALL -> CE
