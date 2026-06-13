"""
dataplatform — Phase 0 + Pillar 1 of the world-class F&O platform.

Provides the point-in-time data foundation everything else builds on:
  * marketcalendar : trading-day/holiday utilities + effective-dated expiry engine
  * contracts      : effective-dated contract-spec resolver (lot/tick/weekly)
  * vendors        : pluggable adapters (bhavcopy NSE/BSE, Kite, synthetic)
  * storage        : Parquet research lake (DuckDB) + operational store (Timescale/SQLite)
  * quality        : data-quality checks
  * ingestion      : EOD pipeline (fetch -> quality -> store -> manifest)

Quick start (offline, zero infra):
    from dataplatform.vendors import SyntheticEODAdapter
    from dataplatform.ingestion import EODIngestionPipeline
    import datetime as dt
    run = EODIngestionPipeline(SyntheticEODAdapter()).ingest_range(
        dt.date(2026, 6, 1), dt.date(2026, 6, 5))
    print(run.total_rows, run.manifest_path)
"""
from . import marketcalendar, contracts, vendors, storage, quality, ingestion
from .config import settings

__version__ = "0.1.0"
__all__ = ["marketcalendar", "contracts", "vendors", "storage",
           "quality", "ingestion", "settings"]
