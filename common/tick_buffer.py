"""#28 Bounded, coalescing market-tick buffer (pure data structure).

Under tick overload the buffer keeps only the LATEST tick per symbol — old
unconsumed quotes are coalesced away — so memory stays bounded regardless of
inbound rate or downstream (DB) slowness. It tracks coalesced/evicted counts for
the overload metrics in #28.

IMPORTANT: order/position lifecycle events must NOT flow through this buffer.
Those go on a separate durable path (the DB-backed command queue, P1#12) and are
never coalesced or dropped. This buffer is for market ticks only.
"""
from __future__ import annotations

from collections import deque


class CoalescingTickBuffer:
    def __init__(self, max_symbols: int = 5000) -> None:
        self.max_symbols = max_symbols
        self._latest: dict = {}
        self._order: deque = deque()
        self.coalesced = 0        # ticks superseded before being consumed
        self.evicted = 0          # symbols dropped to stay within max_symbols

    def put(self, symbol, tick) -> None:
        if symbol in self._latest:
            self.coalesced += 1                 # replacing an unconsumed tick
        else:
            if len(self._latest) >= self.max_symbols:
                oldest = self._order.popleft()  # evict the oldest symbol slot
                self._latest.pop(oldest, None)
                self.evicted += 1
            self._order.append(symbol)
        self._latest[symbol] = tick

    def drain(self) -> dict:
        """Return {symbol: latest_tick} and clear the buffer for the next window."""
        snapshot = dict(self._latest)
        self._latest.clear()
        self._order.clear()
        return snapshot

    def __len__(self) -> int:
        return len(self._latest)
