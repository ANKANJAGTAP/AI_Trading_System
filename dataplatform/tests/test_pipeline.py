"""End-to-end pipeline test on the synthetic adapter (offline, zero infra)."""
import datetime as dt

from dataplatform.vendors import SyntheticEODAdapter
from dataplatform.ingestion import EODIngestionPipeline
from dataplatform.storage import ParquetLake, OperationalStore


def _pipeline(tmp_path):
    lake = ParquetLake(root=tmp_path / "lake")
    store = OperationalStore(sqlite_path=tmp_path / "op.db")
    return EODIngestionPipeline(SyntheticEODAdapter(), lake=lake, store=store), lake, store


def test_ingest_range_end_to_end(tmp_path):
    pipe, lake, store = _pipeline(tmp_path)
    # a Mon-Fri window in 2026 (synthetic adapter ignores holidays for data gen,
    # but the pipeline still skips weekends/holidays)
    run = pipe.ingest_range(dt.date(2026, 6, 1), dt.date(2026, 6, 5))

    assert run.total_rows > 0
    assert run.manifest_path.exists()
    assert run.quarantined_days == []          # clean synthetic data
    assert all(d.ok for d in run.days)

    back = lake.read_eod(underlying="NIFTY")
    assert len(back) > 0
    assert set(back["underlying"]) == {"NIFTY"}
    assert store.count_eod() == run.total_rows


def test_ingest_is_idempotent(tmp_path):
    pipe, lake, store = _pipeline(tmp_path)
    d = dt.date(2026, 6, 1)
    r1 = pipe.ingest_date(d)
    count1 = store.count_eod()
    r2 = pipe.ingest_date(d)               # re-ingest same date
    count2 = store.count_eod()
    assert r1.rows == r2.rows
    assert count1 == count2                 # upsert, not duplicate


def test_weekends_skipped(tmp_path):
    pipe, _, _ = _pipeline(tmp_path)
    # 2026-06-06 and 06-07 are Sat/Sun
    run = pipe.ingest_range(dt.date(2026, 6, 6), dt.date(2026, 6, 7))
    assert run.days == []                    # nothing ingested on a weekend
