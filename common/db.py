"""Async PostgreSQL/TimescaleDB connection pool (asyncpg).

A single shared pool for the app/engine. The migration runner uses its own
short-lived connection (see migrations/runner.py) so it can run before the pool
is initialised.
"""
from __future__ import annotations

import asyncpg

from config.settings import get_settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=s.database_dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
            # IST session so current_date / now() / date logic align with the market.
            server_settings={"timezone": "Asia/Kolkata"},
        )
    return _pool


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        return await init_pool()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def fetch(query: str, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetchval(query: str, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *args)


async def execute(query: str, *args) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)
