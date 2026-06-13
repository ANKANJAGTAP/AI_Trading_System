import datetime as dt

import pandas as pd
import pytest

from dataplatform.vendors import KiteInstruments
from fno_backtest.instruments import bull_call_spread
from fno_signals.execution import to_kite_orders, place_orders
from fno_signals.pipeline import TradeDecision

_EXP = dt.date(2026, 6, 30)


def _instruments():
    rows = [
        {"instrument_token": 2, "tradingsymbol": "NIFTY26JUN22000CE", "name": "NIFTY",
         "expiry": _EXP, "strike": 22000.0, "instrument_type": "CE", "exchange": "NFO", "lot_size": 65},
        {"instrument_token": 4, "tradingsymbol": "NIFTY26JUN22100CE", "name": "NIFTY",
         "expiry": _EXP, "strike": 22100.0, "instrument_type": "CE", "exchange": "NFO", "lot_size": 65},
    ]
    return KiteInstruments(pd.DataFrame(rows))


def _accepted_decision():
    s = bull_call_spread(22000, 22100, qty=65, price_lo=150, price_hi=100)
    return TradeDecision("NIFTY", pd.Timestamp("2026-06-08"), True, None,
                         structure=s, lots=1, qty=65)


def test_to_kite_orders_maps_legs():
    orders = to_kite_orders(_accepted_decision(), _EXP, _instruments())
    assert len(orders) == 2
    buy = next(o for o in orders if o["transaction_type"] == "BUY")
    sell = next(o for o in orders if o["transaction_type"] == "SELL")
    assert buy["tradingsymbol"] == "NIFTY26JUN22000CE" and buy["quantity"] == 65
    assert sell["tradingsymbol"] == "NIFTY26JUN22100CE"
    assert all(o["exchange"] == "NFO" and o["product"] == "NRML" for o in orders)


def test_rejected_decision_yields_no_orders():
    d = TradeDecision("NIFTY", pd.Timestamp("2026-06-08"), False, "gate failed")
    assert to_kite_orders(d, _EXP, _instruments()) == []


def test_place_orders_refuses_without_confirm():
    with pytest.raises(PermissionError):
        place_orders(object(), [{"tradingsymbol": "X"}], confirm=False)
