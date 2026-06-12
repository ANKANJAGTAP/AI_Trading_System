"""Re-entry cooldown (loss-minimisation): after a position/structure closes, block
re-entry on the same instrument/underlying for a configured window. Prevents the
churn loop where a setup is opened, exits at target/stop, and is reopened the next
slow-loop cycle — which bleeds transaction costs and turns trading into thrashing.

Backed by Redis keys with a TTL so the cooldown auto-expires.
"""
from __future__ import annotations

from common.redis_client import get_redis

_PREFIX = "aegis:cooldown:"


async def set_cooldown(key: str, minutes: float) -> None:
    if minutes <= 0:
        return
    r = await get_redis()
    await r.setex(_PREFIX + key, int(minutes * 60), "1")


async def in_cooldown(key: str) -> bool:
    r = await get_redis()
    return bool(await r.exists(_PREFIX + key))
