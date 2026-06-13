"""
Parquet research lake + DuckDB query layer.

The cold lake is where 15-20 years of curated EOD/feature data live for fast,
cheap analytical scans during research. Partitioned by underlying/year/month;
one file per (underlying, trade_date) so re-ingesting a day is idempotent.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from ..config import settings
from ..vendors.base import CANONICAL_EOD_COLUMNS


class ParquetLake:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else settings.lake_dir
        self.eod_root = self.root / "eod_fno"

    # ------------------------------------------------------------------ #
    def _path_for(self, underlying: str, d: dt.date) -> Path:
        return (self.eod_root / f"underlying={underlying}"
                / f"year={d.year:04d}" / f"month={d.month:02d}"
                / f"{underlying}_{d:%Y%m%d}.parquet")

    def write_eod(self, df: pd.DataFrame) -> list[Path]:
        """Write a canonical EOD frame, one parquet file per (underlying, date)."""
        if df.empty:
            return []
        written: list[Path] = []
        df = df[CANONICAL_EOD_COLUMNS].copy()
        # normalise date dtypes to python date for stable partitioning
        for (u, d), part in df.groupby(["underlying", "trade_date"]):
            d = d if isinstance(d, dt.date) else pd.Timestamp(d).date()
            path = self._path_for(u, d)
            path.parent.mkdir(parents=True, exist_ok=True)
            part.to_parquet(path, engine="pyarrow", index=False)
            written.append(path)
        return written

    # ------------------------------------------------------------------ #
    def _glob(self) -> str:
        return str(self.eod_root / "**" / "*.parquet")

    def query(self, sql: str) -> pd.DataFrame:
        """Run DuckDB SQL. Use the table function `eod()` for the EOD dataset.

        Example: lake.query("SELECT underlying, count(*) FROM eod() GROUP BY 1")
        """
        import duckdb
        con = duckdb.connect()
        try:
            con.execute(
                f"CREATE MACRO eod() AS TABLE "
                f"SELECT * FROM read_parquet('{self._glob()}', union_by_name=true)"
            )
            return con.execute(sql).fetchdf()
        finally:
            con.close()

    def read_eod(
        self,
        underlying: str | None = None,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> pd.DataFrame:
        """Convenience reader with optional filters (point-in-time friendly)."""
        import duckdb
        con = duckdb.connect()
        try:
            preds, params = [], []
            if underlying:
                preds.append("underlying = ?"); params.append(underlying)
            if start:
                preds.append("trade_date >= ?"); params.append(start)
            if end:
                preds.append("trade_date <= ?"); params.append(end)
            where = (" WHERE " + " AND ".join(preds)) if preds else ""
            sql = (f"SELECT * FROM read_parquet('{self._glob()}', union_by_name=true)"
                   f"{where} ORDER BY trade_date, underlying, expiry, strike")
            return con.execute(sql, params).fetchdf()
        except duckdb.IOException:
            # no files yet
            from ..vendors.base import empty_canonical
            return empty_canonical()
        finally:
            con.close()
