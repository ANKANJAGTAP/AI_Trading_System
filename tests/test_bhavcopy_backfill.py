"""bhavcopy_backfill pure helpers (no network/lake — heavy imports live in _session_adapter)."""
import datetime as dt
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "bhavcopy_backfill.py")
_spec = importlib.util.spec_from_file_location("bhavcopy_backfill", _PATH)
bb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bb)


def test_format_cutover():
    assert bb.bhavcopy_format_for(dt.date(2024, 7, 7)) == "legacy"   # day before cutover
    assert bb.bhavcopy_format_for(dt.date(2024, 7, 8)) == "udiff"    # cutover day
    assert bb.bhavcopy_format_for(dt.date(2023, 1, 2)) == "legacy"
    assert bb.bhavcopy_format_for(dt.date(2026, 6, 1)) == "udiff"


def test_month_windows_spans_months():
    w = bb.month_windows(dt.date(2024, 1, 15), dt.date(2024, 3, 10))
    assert w == [
        (dt.date(2024, 1, 15), dt.date(2024, 1, 31)),
        (dt.date(2024, 2, 1), dt.date(2024, 2, 29)),    # 2024 is a leap year
        (dt.date(2024, 3, 1), dt.date(2024, 3, 10)),
    ]


def test_month_windows_single_month_and_year_boundary():
    assert bb.month_windows(dt.date(2025, 5, 3), dt.date(2025, 5, 20)) == [
        (dt.date(2025, 5, 3), dt.date(2025, 5, 20))]
    w = bb.month_windows(dt.date(2024, 12, 20), dt.date(2025, 1, 10))
    assert w == [
        (dt.date(2024, 12, 20), dt.date(2024, 12, 31)),
        (dt.date(2025, 1, 1), dt.date(2025, 1, 10)),
    ]
