"""
EOD ingestion pipeline:  vendor -> quality -> lake + operational store -> manifest.

Design choices that matter:
  * Quarantine, don't drop: dates with error-severity issues are written to a
    quarantine area and recorded, never silently discarded.
  * Reproducibility: every run writes a manifest (dates, source, row counts,
    quality summary) so a backtest can pin exactly what data it used.
  * Idempotent: re-ingesting a date overwrites cleanly in both lake and store.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..config import settings
from ..marketcalendar import TradingCalendar
from ..quality import run_quality_checks, QualityReport
from ..storage import ParquetLake, OperationalStore
from ..vendors.base import VendorAdapter


@dataclass
class DayResult:
    trade_date: dt.date
    rows: int
    ok: bool
    errors: int
    warnings: int
    quarantined: bool = False
    quality_summary: str = ""


@dataclass
class RunResult:
    run_id: str
    source: str
    days: list[DayResult] = field(default_factory=list)
    manifest_path: Path | None = None

    @property
    def total_rows(self) -> int:
        return sum(d.rows for d in self.days)

    @property
    def quarantined_days(self) -> list[dt.date]:
        return [d.trade_date for d in self.days if d.quarantined]


class EODIngestionPipeline:
    def __init__(
        self,
        adapter: VendorAdapter,
        lake: ParquetLake | None = None,
        store: OperationalStore | None = None,
        calendar: TradingCalendar | None = None,
        block_store_on_error: bool = True,
    ):
        self.adapter = adapter
        self.lake = lake or ParquetLake()
        self.store = store or OperationalStore()
        self.calendar = calendar or TradingCalendar.from_seed()
        self.block_store_on_error = block_store_on_error
        settings.ensure_dirs()
        self.quarantine_dir = settings.home / "quarantine"

    # ------------------------------------------------------------------ #
    def ingest_date(self, trade_date: dt.date) -> DayResult:
        df = self.adapter.fetch_eod_fno(trade_date)
        report: QualityReport = run_quality_checks(df)

        if report.ok:
            self.lake.write_eod(df)
            self.store.write_eod(df)
            quarantined = False
        else:
            self._quarantine(trade_date, df)
            if not self.block_store_on_error:
                self.lake.write_eod(df)
                self.store.write_eod(df)
            quarantined = True

        return DayResult(
            trade_date=trade_date, rows=len(df), ok=report.ok,
            errors=report.errors, warnings=report.warnings,
            quarantined=quarantined, quality_summary=report.summary(),
        )

    def ingest_range(
        self, start: dt.date, end: dt.date, skip_non_trading: bool = True
    ) -> RunResult:
        run = RunResult(run_id=uuid.uuid4().hex[:12], source=self.adapter.id)
        cur = start
        while cur <= end:
            if skip_non_trading and not self.calendar.is_trading_day(cur):
                cur += dt.timedelta(days=1)
                continue
            try:
                run.days.append(self.ingest_date(cur))
            except Exception as e:  # noqa: BLE001 — record and continue
                run.days.append(DayResult(cur, 0, False, 1, 0, True,
                                          f"fetch failed: {e}"))
            cur += dt.timedelta(days=1)
        run.manifest_path = self._write_manifest(run, start, end)
        return run

    # ------------------------------------------------------------------ #
    def _quarantine(self, trade_date: dt.date, df: pd.DataFrame) -> None:
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        if not df.empty:
            df.to_parquet(self.quarantine_dir / f"{self.adapter.id}_{trade_date:%Y%m%d}.parquet",
                          engine="pyarrow", index=False)

    def _write_manifest(self, run: RunResult, start: dt.date, end: dt.date) -> Path:
        settings.manifest_dir.mkdir(parents=True, exist_ok=True)
        path = settings.manifest_dir / f"ingest_{run.source}_{run.run_id}.json"
        manifest = {
            "run_id": run.run_id,
            "source": run.source,
            "store_backend": self.store.backend,
            "range": {"start": str(start), "end": str(end)},
            "created_utc": dt.datetime.utcnow().isoformat() + "Z",
            "total_rows": run.total_rows,
            "days": [
                {
                    "date": str(d.trade_date), "rows": d.rows, "ok": d.ok,
                    "errors": d.errors, "warnings": d.warnings,
                    "quarantined": d.quarantined,
                }
                for d in run.days
            ],
            "quarantined_days": [str(x) for x in run.quarantined_days],
        }
        path.write_text(json.dumps(manifest, indent=2))
        return path
