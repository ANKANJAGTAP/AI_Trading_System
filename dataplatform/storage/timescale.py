"""
Operational store writer.

Production: set TIMESCALE_DSN and rows go to TimescaleDB (schema.sql).
Dev/offline: with no DSN, the same API writes to a local SQLite file so the
whole pipeline runs with zero infrastructure. The EOD table is idempotent
(upsert on the natural key), so re-ingesting a date is safe.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from ..config import settings
from ..vendors.base import CANONICAL_EOD_COLUMNS

_EOD_KEY = ["trade_date", "underlying", "instrument", "opt_type", "expiry", "strike"]


class OperationalStore:
    def __init__(self, dsn: str | None = None, sqlite_path: Path | None = None):
        self.dsn = dsn if dsn is not None else settings.timescale_dsn
        self.sqlite_path = Path(sqlite_path) if sqlite_path else settings.sqlite_path
        self.backend = "timescale" if self.dsn else "sqlite"

    # ------------------------------------------------------------------ #
    def _sqlite(self) -> sqlite3.Connection:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.sqlite_path)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS eod_fno (
                trade_date TEXT, underlying TEXT, exchange TEXT, instrument TEXT,
                opt_type TEXT, expiry TEXT, strike REAL,
                open REAL, high REAL, low REAL, close REAL, settle REAL,
                volume INTEGER, oi INTEGER, oi_change INTEGER, source TEXT,
                PRIMARY KEY (trade_date, underlying, instrument, opt_type, expiry, strike)
            )
            """
        )
        return con

    def write_eod(self, df: pd.DataFrame) -> int:
        """Upsert canonical EOD rows. Returns row count written."""
        if df.empty:
            return 0
        df = df[CANONICAL_EOD_COLUMNS].copy()
        df["trade_date"] = df["trade_date"].astype(str)
        df["expiry"] = df["expiry"].astype(str)
        if self.backend == "sqlite":
            return self._write_sqlite(df)
        return self._write_timescale(df)

    def _write_sqlite(self, df: pd.DataFrame) -> int:
        con = self._sqlite()
        try:
            cols = ",".join(CANONICAL_EOD_COLUMNS)
            ph = ",".join(["?"] * len(CANONICAL_EOD_COLUMNS))
            con.executemany(
                f"INSERT OR REPLACE INTO eod_fno ({cols}) VALUES ({ph})",
                df.itertuples(index=False, name=None),
            )
            con.commit()
            return len(df)
        finally:
            con.close()

    def _write_timescale(self, df: pd.DataFrame) -> int:
        import psycopg2
        from psycopg2.extras import execute_values
        cols = ",".join(CANONICAL_EOD_COLUMNS)
        updates = ",".join(
            f"{c}=EXCLUDED.{c}" for c in CANONICAL_EOD_COLUMNS if c not in _EOD_KEY
        )
        sql = (
            f"INSERT INTO eod_fno ({cols}) VALUES %s "
            f"ON CONFLICT ({','.join(_EOD_KEY)}) DO UPDATE SET {updates}"
        )
        con = psycopg2.connect(self.dsn)
        try:
            with con.cursor() as cur:
                execute_values(cur, sql, list(df.itertuples(index=False, name=None)))
            con.commit()
            return len(df)
        finally:
            con.close()

    def count_eod(self) -> int:
        if self.backend == "sqlite":
            con = self._sqlite()
            try:
                return con.execute("SELECT count(*) FROM eod_fno").fetchone()[0]
            finally:
                con.close()
        import psycopg2
        con = psycopg2.connect(self.dsn)
        try:
            with con.cursor() as cur:
                cur.execute("SELECT count(*) FROM eod_fno")
                return cur.fetchone()[0]
        finally:
            con.close()
