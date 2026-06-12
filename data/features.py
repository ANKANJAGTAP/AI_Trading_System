"""Per-candle feature cache (TD-2).

The slow loop and the market scanner rebuild full-history indicator/context values
every cycle (~60s) even though candles only close every 1-15m. This memoises the
expensive computation per (token, interval), recomputing only when a newer candle
has closed. Loading the latest candle to read its timestamp stays cheap; the
indicator math (the real cost) is skipped on a hit.

    last_ts = df.index[-1]
    ctx = await get_or_compute(token, "5m", last_ts, lambda: build_ctx(df, ...))
"""
from __future__ import annotations

from typing import Awaitable, Callable

_cache: dict[tuple[int, str], tuple] = {}  # (token, interval) -> (last_ts, value)


async def get_or_compute(token: int, interval: str, last_ts, factory: Callable[[], Awaitable]):
    """Return the cached value if the latest candle ts is unchanged, else recompute."""
    key = (token, interval)
    hit = _cache.get(key)
    if hit is not None and hit[0] == last_ts:
        return hit[1]
    value = await factory()
    _cache[key] = (last_ts, value)
    return value


def invalidate(token: int, interval: str | None = None) -> None:
    if interval is None:
        for k in [k for k in _cache if k[0] == token]:
            _cache.pop(k, None)
    else:
        _cache.pop((token, interval), None)


def clear() -> None:
    _cache.clear()
