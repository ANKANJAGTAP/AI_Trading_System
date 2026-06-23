"""DhanHQ historical normalisation (pure — no network/DB)."""
from datetime import timezone

from dataplatform.vendors.dhan import (DHAN_INTERVAL, dhan_to_candle_rows,
                                       parse_scrip_master)


def test_dhan_to_candle_rows():
    resp = {"open": [100, 101], "high": [102, 103], "low": [99, 100],
            "close": [101, 102.5], "volume": [500, 600],
            "open_interest": [10, None], "timestamp": [1700000000, 1700000300]}
    rows = dhan_to_candle_rows(resp, token=738561, interval="5m", tz=timezone.utc)
    assert len(rows) == 2
    assert rows[0][1] == 738561 and rows[0][2] == "5m"
    assert rows[0][3] == 100.0 and rows[0][6] == 101.0 and rows[0][7] == 500
    assert rows[0][0].year == 2023                 # epoch 1700000000 -> 2023-11-14 UTC
    assert rows[1][8] == 0                          # open_interest None -> 0


def test_dhan_skips_incomplete_and_mismatched_lengths():
    resp = {"open": [1, 2, 3], "high": [1, 2, 3], "low": [1, 2, 3],
            "close": [1, None, 3], "volume": [1, 2, 3], "timestamp": [100, 200, None]}
    rows = dhan_to_candle_rows(resp, 1, "1m", tz=timezone.utc)
    assert len(rows) == 1                           # idx1 close None, idx2 ts None -> skipped


def test_dhan_empty():
    assert dhan_to_candle_rows({}, 1, "1m") == []
    assert dhan_to_candle_rows(None, 1, "1m") == []


def test_parse_scrip_master_dhan_headers():
    csv_text = (
        "SEM_SMST_SECURITY_ID,SEM_TRADING_SYMBOL,SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_INSTRUMENT_NAME\n"
        "1333,HDFCBANK,NSE,E,EQUITY\n"
        "2885,RELIANCE,NSE,E,EQUITY\n"
    )
    m = parse_scrip_master(csv_text)
    assert m[("NSE", "RELIANCE")]["security_id"] == "2885"
    assert m[("NSE", "HDFCBANK")]["instrument"] == "EQUITY"


def test_parse_scrip_master_fuzzy_headers():
    m = parse_scrip_master("Security Id,Trading Symbol,Exchange\n11536,TCS,NSE\n")
    assert m[("NSE", "TCS")]["security_id"] == "11536"


def test_interval_map():
    assert DHAN_INTERVAL["5m"] == "5" and DHAN_INTERVAL["60m"] == "60"
