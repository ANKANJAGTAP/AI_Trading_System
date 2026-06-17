"""Forward-only SQL migration runner.

Applies `migrations/sql/*.sql` in lexical order, each in its own transaction, and
records applied versions in `schema_migrations`. Idempotent: already-applied
files are skipped. Raw SQL (not an ORM) keeps the TimescaleDB hypertable DDL
transparent and version-controlled.
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import asyncpg

from common.logging import configure_logging, get_logger
from config.settings import get_settings

log = get_logger("migrations")
SQL_DIR = Path(__file__).parent / "sql"

# Session advisory-lock key so concurrent runners (api + engine both run migrate
# on startup) serialise instead of racing on CREATE TABLE / schema_migrations.
_LOCK_KEY = 727274


def detect_drift(stored: dict, current: dict) -> list:
    """#16: versions whose on-disk checksum no longer matches what was applied.
    Rows with no recorded checksum are skipped; pending files (not yet applied)
    and recorded migrations whose file is absent are not drift."""
    drift = [
        v for v, s in stored.items()
        if s and v in current and current[v] != s
    ]
    return sorted(drift)


async def _ensure_migrations_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            name       TEXT,
            checksum   TEXT,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


async def run_migrations() -> None:
    configure_logging()
    settings = get_settings()
    conn = await asyncpg.connect(dsn=settings.database_dsn)
    try:
        # Block until we hold the lock; a concurrent runner finishes first and
        # this process then finds every migration already applied.
        await conn.execute("SELECT pg_advisory_lock($1)", _LOCK_KEY)
        await _ensure_migrations_table(conn)
        rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
        applied = {r["version"]: r["checksum"] for r in rows}
        files = sorted(SQL_DIR.glob("*.sql"))
        if not files:
            log.warning("no_migration_files", dir=str(SQL_DIR))
            return

        # #16 drift detection: an already-applied migration whose file changed is a
        # forward-only violation. Warn always; fail startup ONLY when strict, so a
        # checksum drift never silently bricks a running deployment by default.
        current = {p.stem: hashlib.sha256(p.read_text(encoding="utf-8").encode()).hexdigest()
                   for p in files}
        drift = detect_drift(applied, current)
        if drift:
            strict = get_settings().migration_strict
            log.warning("migration_drift_detected", versions=drift, strict=strict)
            if strict:
                raise RuntimeError(f"migration drift on {drift} (migration_strict enabled)")

        newly = 0
        for path in files:
            version = path.stem
            if version in applied:
                log.debug("migration_skip", version=version)
                continue
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            log.info("migration_apply", version=version)
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) "
                    "VALUES ($1, $2, $3)",
                    version,
                    path.name,
                    checksum,
                )
            newly += 1
        log.info("migrations_complete", total=len(files), applied=newly)
    finally:
        try:
            await conn.execute("SELECT pg_advisory_unlock($1)", _LOCK_KEY)
        finally:
            await conn.close()


async def status() -> None:
    """#16: print applied / pending / drift without applying anything.
    Run with: python -m migrations.runner status"""
    configure_logging()
    conn = await asyncpg.connect(dsn=get_settings().database_dsn)
    try:
        await _ensure_migrations_table(conn)
        rows = await conn.fetch("SELECT version, checksum FROM schema_migrations ORDER BY version")
        applied = {r["version"]: r["checksum"] for r in rows}
        current = {p.stem: hashlib.sha256(p.read_text(encoding="utf-8").encode()).hexdigest()
                   for p in sorted(SQL_DIR.glob("*.sql"))}
        pending = [v for v in current if v not in applied]
        print(f"applied={len(applied)} pending={pending} drift={detect_drift(applied, current)}")
    finally:
        await conn.close()


if __name__ == "__main__":
    import sys
    asyncio.run(status() if len(sys.argv) > 1 and sys.argv[1] == "status" else run_migrations())
