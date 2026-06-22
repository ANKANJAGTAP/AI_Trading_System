"""TrueData intraday bar normalisation (pure — no SDK/DB)."""
from types import SimpleNamespace

from dataplatform.vendors.truedata import bars_to_candle_rows, normalize_bar


def test_normalize_dict_bar():
    b = {"time": "2026-06-22T09:15", "open": 100, "high": 101, "low": 99,
         "close": 100.5, "volume": 500, "oi": 12}
    n = normalize_bar(b)
    assert n["ts"] == "2026-06-22T09:15" and n["open"] == 100
    assert n["close"] == 100.5 and n["volume"] == 500 and n["oi"] == 12


def test_normalize_object_bar_and_none_defaults():
    b = SimpleNamespace(timestamp="t1", open=1, high=2, low=0.5, close=1.5, volume=None, oi=None)
    n = normalize_bar(b)
    assert n["ts"] == "t1" and n["volume"] == 0 and n["oi"] == 0   # None -> 0, alt ts key


def test_bars_to_candle_rows_maps_and_skips_incomplete():
    bars = [
        {"time": "t1", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 500, "oi": 10},
        {"time": "t2", "open": 100.5, "high": 102, "low": 100, "close": 101, "volume": 600},  # no oi -> 0
        {"time": None, "open": 1, "close": 1},        # no ts -> skipped
        {"time": "t3", "open": None, "close": 1},     # no open -> skipped
    ]
    rows = bars_to_candle_rows(bars, token=738561, interval="5m")
    assert len(rows) == 2
    assert rows[0] == ("t1", 738561, "5m", 100.0, 101.0, 99.0, 100.5, 500, 10)
    assert rows[1][8] == 0                            # oi defaults to 0
    assert all(r[1] == 738561 and r[2] == "5m" for r in rows)


def test_empty_inputs():
    assert bars_to_candle_rows([], 1, "1m") == []
    assert bars_to_candle_rows(None, 1, "1m") == []
