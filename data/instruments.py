"""Instruments master loader (spec §7).

Loads the Kite instruments dump (full or a configured set of exchanges) into the
`instruments` table and provides symbol<->token<->lot/expiry/strike lookups.
Refreshed daily (scheduler). All Kite REST goes through the RateGovernor.

Note: Kite returns `exchange_token` as a string and `expiry` as a date or '' —
both are normalised here.
"""
from __future__ import annotations

from common.db import fetch, fetchrow, get_pool
from common.logging import get_logger

log = get_logger("instruments")

_UPSERT = """
INSERT INTO instruments (
    instrument_token, exchange_token, tradingsymbol, name, last_price,
    expiry, strike, tick_size, lot_size, instrument_type, segment, exchange, updated_at
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12, now())
ON CONFLICT (instrument_token) DO UPDATE SET
    tradingsymbol = EXCLUDED.tradingsymbol,
    name          = EXCLUDED.name,
    last_price    = EXCLUDED.last_price,
    expiry        = EXCLUDED.expiry,
    strike        = EXCLUDED.strike,
    tick_size     = EXCLUDED.tick_size,
    lot_size      = EXCLUDED.lot_size,
    instrument_type = EXCLUDED.instrument_type,
    segment       = EXCLUDED.segment,
    exchange      = EXCLUDED.exchange,
    updated_at    = now()
"""


def _as_int(x) -> int | None:
    return int(x) if x not in (None, "") else None


def _as_num(x) -> float | None:
    return float(x) if x not in (None, "") else None


def _row(i: dict) -> tuple:
    return (
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


async def refresh_instruments(adapter, governor, exchanges: list[str] | None = None) -> int:
    """Fetch the instruments dump and upsert it. exchanges=None => full dump."""
    insts: list[dict] = []
    if exchanges:
        for ex in exchanges:
            insts.extend(await governor.call("other", adapter.instruments, ex))
    else:
        insts = await governor.call("other", adapter.instruments)

    rows = [_row(i) for i in insts]
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for start in range(0, len(rows), 5000):
                await conn.executemany(_UPSERT, rows[start : start + 5000])
        total = await conn.fetchval("SELECT count(*) FROM instruments")
    log.info("instruments_refreshed", fetched=len(rows), total_in_db=total)
    return len(rows)


# --- lookups -----------------------------------------------------------------
async def get_instrument(instrument_token: int) -> dict | None:
    row = await fetchrow("SELECT * FROM instruments WHERE instrument_token = $1", instrument_token)
    return dict(row) if row else None


async def get_by_symbol(exchange: str, tradingsymbol: str) -> dict | None:
    row = await fetchrow(
        "SELECT * FROM instruments WHERE exchange = $1 AND tradingsymbol = $2",
        exchange, tradingsymbol,
    )
    return dict(row) if row else None


async def resolve(exchange_symbol: str) -> dict | None:
    """Resolve an 'EXCHANGE:TRADINGSYMBOL' string to its instrument row."""
    exchange, _, tradingsymbol = exchange_symbol.partition(":")
    return await get_by_symbol(exchange, tradingsymbol)


async def get_token(exchange_symbol: str) -> int | None:
    inst = await resolve(exchange_symbol)
    return inst["instrument_token"] if inst else None


async def resolve_tokens(exchange_symbols: list[str]) -> dict[str, int]:
    """Map a list of 'EXCHANGE:SYMBOL' to {symbol: token}, skipping unknowns."""
    out: dict[str, int] = {}
    for es in exchange_symbols:
        tok = await get_token(es)
        if tok is not None:
            out[es] = tok
        else:
            log.warning("symbol_not_in_instruments", symbol=es)
    return out


async def front_month_future(name: str, exchange: str = "MCX", min_dte: int = 3) -> dict | None:
    """Nearest non-expiring futures contract for `name` (contract symbols roll
    monthly, so callers configure NAMES and resolve the live contract here).
    `min_dte` skips the expiry-roll window — never trade a dying contract."""
    row = await fetchrow(
        "SELECT * FROM instruments WHERE exchange=$1 AND name=$2 AND instrument_type='FUT' "
        "AND expiry >= CURRENT_DATE + $3::int ORDER BY expiry LIMIT 1",
        exchange, name, int(min_dte))
    return dict(row) if row else None
