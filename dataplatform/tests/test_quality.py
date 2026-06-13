import datetime as dt

from dataplatform.quality import run_quality_checks
from dataplatform.vendors import SyntheticEODAdapter, empty_canonical


def _clean():
    return SyntheticEODAdapter().fetch_eod_fno(dt.date(2026, 6, 10))


def test_clean_data_passes():
    rep = run_quality_checks(_clean())
    assert rep.rows > 0
    assert rep.ok is True
    assert rep.errors == 0


def test_crossed_bar_detected():
    df = _clean()
    df.loc[df.index[0], "high"] = df.loc[df.index[0], "low"] - 1  # high < low
    rep = run_quality_checks(df)
    assert not rep.ok
    assert any(i.check == "crossed_high_low" for i in rep.issues)


def test_duplicate_keys_detected():
    df = _clean()
    df = df._append(df.iloc[0], ignore_index=True)  # duplicate natural key
    rep = run_quality_checks(df)
    assert any(i.check == "duplicate_keys" for i in rep.issues)


def test_expiry_before_trade_date_detected():
    df = _clean()
    df.loc[df.index[0], "expiry"] = dt.date(2000, 1, 1)
    rep = run_quality_checks(df)
    assert any(i.check == "expiry_before_trade_date" for i in rep.issues)


def test_bad_strike_detected():
    df = _clean()
    opt_idx = df[df["instrument"] == "OPT"].index[0]
    df.loc[opt_idx, "strike"] = 0
    rep = run_quality_checks(df)
    assert any(i.check == "bad_option_strike" for i in rep.issues)


def test_missing_column_is_schema_error():
    df = _clean().drop(columns=["close"])
    rep = run_quality_checks(df)
    assert not rep.ok
    assert any(i.check == "schema" for i in rep.issues)


def test_empty_frame_warns():
    rep = run_quality_checks(empty_canonical())
    assert rep.rows == 0
    assert rep.ok  # empty is a warning, not an error
