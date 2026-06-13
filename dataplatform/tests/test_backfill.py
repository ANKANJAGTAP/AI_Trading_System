import datetime as dt

from dataplatform.backfill import build_option_universe, run_backfill
from dataplatform.vendors import SyntheticEODAdapter
from dataplatform.storage import ParquetLake, OperationalStore


def test_universe_counts_and_futures():
    specs = build_option_universe("NIFTY", dt.date(2026, 6, 8), atm_spot=22000.0,
                                  n_strikes=5, step=50.0)
    n_exp = len(set(s["expiry"] for s in specs))
    assert n_exp >= 1
    # each expiry: 1 future + (2*5+1)*2 options = 23
    assert len(specs) == n_exp * 23
    futs = [s for s in specs if s["opt_type"] == ""]
    assert futs and all(s["strike"] == 0.0 for s in futs)


def test_finnifty_universe_is_monthly_only():
    specs = build_option_universe("FINNIFTY", dt.date(2026, 6, 8), 22000.0,
                                  n_strikes=3, step=50.0)
    assert len(set(s["expiry"] for s in specs)) == 1   # weekly discontinued


def test_run_backfill_with_synthetic_adapter(tmp_path):
    lake = ParquetLake(root=tmp_path / "lake")
    store = OperationalStore(sqlite_path=tmp_path / "op.db")
    run = run_backfill(SyntheticEODAdapter(), dt.date(2026, 6, 1), dt.date(2026, 6, 3),
                       lake=lake, store=store)
    assert run.total_rows > 0
    assert run.quarantined_days == []
    assert store.count_eod() == run.total_rows
