import datetime as dt

import pytest

from dataplatform.contracts import ContractSpecResolver
from dataplatform.contracts.models import SpecRecord


def test_lot_size_point_in_time():
    r = ContractSpecResolver()
    # Verified NIFTY lot timeline: 25 -> 75 (2024-11-20) -> 65 (2025-12-31)
    assert r.lot_size("NIFTY", dt.date(2024, 1, 15)) == 25     # pre Nov-2024
    assert r.lot_size("NIFTY", dt.date(2025, 6, 15)) == 75     # Nov2024..Dec2025
    assert r.lot_size("NIFTY", dt.date(2026, 6, 15)) == 65     # current


def test_weekly_available_flag():
    r = ContractSpecResolver()
    assert r.weekly_available("FINNIFTY", dt.date(2023, 6, 1)) is True
    assert r.weekly_available("FINNIFTY", dt.date(2025, 6, 1)) is False


def test_tick_size():
    r = ContractSpecResolver()
    assert r.tick_size("NIFTY", dt.date(2026, 1, 1)) == 0.05


def test_missing_raises():
    r = ContractSpecResolver()
    with pytest.raises(KeyError):
        r.as_of("NIFTY", "lot_size", dt.date(1990, 1, 1))  # before any record
    with pytest.raises(KeyError):
        r.as_of("NIFTY", "nonexistent_attr", dt.date(2026, 1, 1))


def test_unverified_surface():
    # The shipped seed is now fully verified against NSE/BSE circulars.
    assert ContractSpecResolver().unverified() == []
    # The surfacing mechanism still flags any verify=True record that's added.
    flagged = SpecRecord("X", "lot_size", "1", dt.date(2020, 1, 1), None, verify=True)
    ok = SpecRecord("Y", "lot_size", "1", dt.date(2020, 1, 1), None, verify=False)
    unver = ContractSpecResolver(specs=[flagged, ok]).unverified()
    assert unver == [flagged]
    assert all(s.verify for s in unver)
