"""External-data provider interfaces (spec §7) for data Kite does NOT give.

Concrete implementations are swappable. Stubs let the pipelines + tests run before
the real Indian fundamentals API / F&O ban-list source is wired.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class FundamentalsProvider(ABC):
    @abstractmethod
    async def get_fundamentals(self, symbol: str) -> dict:
        """-> {market_cap_cr, roe, revenue_growth, eps_growth, debt_equity,
               promoter_holding_trend, avg_daily_volume, ...}"""


class StubFundamentalsProvider(FundamentalsProvider):
    """Returns injected fundamentals (tests / pre-integration). Swap for the real API."""

    def __init__(self, data: dict | None = None) -> None:
        self._data = data or {}

    async def get_fundamentals(self, symbol: str) -> dict:
        return self._data.get(symbol, {})


class BanListProvider(ABC):
    @abstractmethod
    async def is_banned(self, symbol: str) -> bool:
        ...


class StubBanListProvider(BanListProvider):
    def __init__(self, banned: set[str] | None = None) -> None:
        self._banned = set(banned or [])

    async def is_banned(self, symbol: str) -> bool:
        return symbol in self._banned


class NewsProvider(ABC):
    """News feed for the LLM context layer (consumed in Phase 5)."""

    @abstractmethod
    async def get_news(self, symbol_or_index: str, since) -> list[dict]:
        ...
