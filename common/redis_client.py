"""Shared async Redis client (live state, fast<->slow loop bus, locks)."""
from __future__ import annotations

import redis.asyncio as aioredis

from config.settings import get_settings

_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        s = get_settings()
        _client = aioredis.from_url(s.redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
