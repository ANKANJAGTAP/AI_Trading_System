"""Phase 0 acceptance check.

Verifies the spec's Phase 0 acceptance criteria against REAL infrastructure:
  1. DB schema  — all required tables exist; ticks/candles/audit_log are hypertables.
  2. Kite auth  — automated TOTP login (or cached token) succeeds.
  3. margins()  — a live margins() call returns real data.
  4. instruments() — a live instruments() call returns real data AND persists to DB.

Exit code 0 = PASS, 1 = FAIL. Kite checks are skipped (reported FAIL) if creds
are absent; the DB check runs regardless.

Usage: python scripts/verify_phase0.py
"""
from __future__ import annotations

import asyncio
import sys

from broker.kite_adapter import KiteAdapter
from common.db import close_pool, get_pool, init_pool
from common.logging import configure_logging, get_logger
from config.settings import get_settings

log = get_logger("verify_phase0")

REQUIRED_TABLES = {
    "instruments", "ticks", "candles", "orders", "fills", "positions",
    "signals", "gate_results", "audit_log", "daily_pnl", "config_state",
    "schema_migrations",
}
REQUIRED_HYPERTABLES = {"ticks", "candles", "audit_log"}

_INSERT_INSTRUMENT = """
INSERT INTO instruments (
    instrument_token, exchange_token, tradingsymbol, name, last_price,
    expiry, strike, tick_size, lot_size, instrument_type, segment, exchange, updated_at
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12, now())
ON CONFLICT (instrument_token) DO UPDATE SET
    last_price = EXCLUDED.last_price,
    lot_size   = EXCLUDED.lot_size,
    updated_at = now()
"""


def _as_int(x) -> int | None:
    return int(x) if x not in (None, "") else None


def _as_num(x) -> float | None:
    return float(x) if x not in (None, "") else None


def check_margins(adapter: KiteAdapter) -> tuple[bool, str]:
    # Equity segment is the primary capital source. The combined margins() call can
    # fail with an RMS error if a segment (e.g. commodity) isn't enabled, so try the
    # equity segment first and fall back to the combined call.
    try:
        m = adapter.margins("equity")
        bal = m.get("net", (m.get("available") or {}).get("live_balance"))
        return True, f"equity net={bal}"
    except Exception as e1:
        try:
            m = adapter.margins()
            eq = (m.get("equity") or {}).get("net")
            return True, f"combined equity net={eq}"
        except Exception as e2:
            hint = ""
            if "not registered" in (str(e1) + str(e2)).lower():
                hint = (
                    " | HINT: account likely has no trading segment activated "
                    "(profile.exchanges is empty) — activate the equity segment "
                    "(+ add funds) in Zerodha Console, then re-run."
                )
            return False, f"equity: {e1} | combined: {e2}{hint}"


async def check_db_schema() -> tuple[bool, str]:
    pool = await init_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        names = {r["tablename"] for r in rows}
        try:
            ht_rows = await conn.fetch(
                "SELECT hypertable_name FROM timescaledb_information.hypertables"
            )
            hypertables = {r["hypertable_name"] for r in ht_rows}
        except Exception as exc:  # timescaledb not installed
            return False, f"timescaledb hypertable view unavailable: {exc}"

    missing_tables = REQUIRED_TABLES - names
    missing_ht = REQUIRED_HYPERTABLES - hypertables
    ok = not missing_tables and not missing_ht
    detail = (
        f"tables_ok={not missing_tables} (missing={missing_tables or 'none'}); "
        f"hypertables={sorted(hypertables) or 'none'} "
        f"(missing={missing_ht or 'none'})"
    )
    return ok, detail


async def persist_instruments(adapter: KiteAdapter) -> tuple[bool, str]:
    # Bound the acceptance check to NSE (~2k rows); full multi-exchange master
    # load is the Phase 1 instruments loader.
    insts = adapter.instruments("NSE")
    rows = [
        (
            _as_int(i["instrument_token"]),
            _as_int(i.get("exchange_token")),
            i["tradingsymbol"],
            i.get("name"),
            _as_num(i.get("last_price")),
            i.get("expiry") or None,
            _as_num(i.get("strike")),
            _as_num(i.get("tick_size")),
            _as_int(i.get("lot_size")),
            i.get("instrument_type"),
            i.get("segment"),
            i.get("exchange"),
        )
        for i in insts
    ]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(_INSERT_INSTRUMENT, rows)
        count = await conn.fetchval("SELECT count(*) FROM instruments")
    ok = count and count > 0
    return bool(ok), f"fetched={len(insts)} NSE instruments; rows_in_db={count}"


async def main() -> None:
    configure_logging()
    settings = get_settings()
    results: dict[str, tuple[bool, str]] = {}

    # 1. DB schema
    try:
        results["db_schema"] = await check_db_schema()
    except Exception as exc:
        results["db_schema"] = (False, f"error: {exc}")

    # 2-4. Kite auth + margins + instruments
    have_creds = bool(
        settings.kite_api_key and settings.kite_user_id and settings.kite_totp_secret
    )
    if not have_creds:
        msg = "Kite credentials not set in .env"
        results["kite_auth"] = (False, msg)
        results["margins"] = (False, "skipped (no creds)")
        results["instruments_persist"] = (False, "skipped (no creds)")
    else:
        try:
            adapter = KiteAdapter(settings)
            token = adapter.ensure_token()
            results["kite_auth"] = (bool(token), "token acquired / refreshed")
            results["margins"] = check_margins(adapter)
            try:
                results["instruments_persist"] = await persist_instruments(adapter)
            except Exception as exc:
                results["instruments_persist"] = (False, f"error: {exc}")
        except Exception as exc:
            results["kite_auth"] = (False, f"error: {exc}")
            results["margins"] = (False, "skipped (auth failed)")
            results["instruments_persist"] = (False, "skipped (auth failed)")

    await close_pool()

    # Summary
    print("\n=== PHASE 0 ACCEPTANCE ===")
    overall = True
    for name, (passed, detail) in results.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
        overall = overall and passed
    print("==========================")
    print("RESULT:", "PASS ✅" if overall else "FAIL ❌")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    asyncio.run(main())
