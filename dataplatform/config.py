"""
Central configuration for the data platform.

Everything here is overridable via environment variables so the same code runs
on your laptop (Parquet lake + SQLite fallback) and in production
(TimescaleDB + object storage) without edits.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


# Repo-root-relative data directory by default. Override with DATAPLATFORM_HOME.
_DEFAULT_HOME = Path(_env("DATAPLATFORM_HOME", str(Path.home() / ".aitrading_data")))


@dataclass(frozen=True)
class Settings:
    # --- filesystem layout ---
    home: Path = _DEFAULT_HOME
    raw_dir: Path = field(default=None)        # immutable raw vendor downloads
    lake_dir: Path = field(default=None)       # curated Parquet research lake
    manifest_dir: Path = field(default=None)   # dataset version manifests

    # --- operational database (TimescaleDB in prod; SQLite fallback for dev) ---
    # If TIMESCALE_DSN is set we use Postgres/Timescale; otherwise a local SQLite file.
    timescale_dsn: str | None = os.environ.get("TIMESCALE_DSN")
    sqlite_path: Path = field(default=None)

    # --- instrument universe for Phase A ---
    underlyings: tuple[str, ...] = ("NIFTY", "FINNIFTY", "SENSEX")

    def __post_init__(self):
        # dataclass is frozen, so set derived paths via object.__setattr__
        object.__setattr__(self, "raw_dir", self.home / "raw")
        object.__setattr__(self, "lake_dir", self.home / "lake")
        object.__setattr__(self, "manifest_dir", self.home / "manifests")
        object.__setattr__(self, "sqlite_path", self.home / "operational.db")

    def ensure_dirs(self) -> None:
        for p in (self.home, self.raw_dir, self.lake_dir, self.manifest_dir):
            p.mkdir(parents=True, exist_ok=True)


# Exchange/underlying → exchange mapping for Phase A
EXCHANGE_OF = {
    "NIFTY": "NSE",
    "FINNIFTY": "NSE",
    "SENSEX": "BSE",
}

settings = Settings()
