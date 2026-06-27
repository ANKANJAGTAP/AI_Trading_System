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


def parse_secban(text: str) -> set[str]:
    """NSE fo_secban.csv -> set of banned symbols (UPPER). Rows are 'serial,SYMBOL';
    the header/date line (non-numeric first field) is skipped. Pure — unit-tested."""
    out: set[str] = set()
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0].isdigit() and parts[1]:
            out.add(parts[1].upper())
    return out


class NSEBanListProvider(BanListProvider):
    """NSE's daily F&O 'securities in ban period' list, cached per trading day.

    Only STOCK F&O symbols are ever banned (position-limit breaches); index underlyings
    (NIFTY/FINNIFTY/...) are never on it — so this is a no-op for the index sleeve and a
    real guard once stock F&O is traded. `fetcher` (async () -> csv text) is injectable
    for tests / to supply a cookie-warmed session. On a fetch error it keeps the last
    list (empty until the first success -> nothing banned), so the index path is safe."""

    URL = "https://nsearchives.nseindia.com/content/fo/fo_secban.csv"

    def __init__(self, fetcher=None) -> None:
        self._fetch = fetcher or self._default_fetch
        self._banned: set[str] = set()
        self._day = None

    async def _default_fetch(self) -> str:
        import asyncio
        import urllib.request
        from dataplatform.vendors.nse_bhavcopy import NSE_HEADERS

        def _get() -> str:
            req = urllib.request.Request(self.URL, headers=NSE_HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="replace")
        return await asyncio.to_thread(_get)

    async def _refresh(self) -> set[str]:
        from common.market_time import today_ist
        day = today_ist()
        if self._day == day:
            return self._banned
        try:
            self._banned = parse_secban(await self._fetch())
            self._day = day
        except Exception:  # noqa: BLE001 — keep last list, retry next call (safe for index sleeve)
            pass
        return self._banned

    async def is_banned(self, symbol: str) -> bool:
        return (symbol or "").upper() in await self._refresh()


class NewsProvider(ABC):
    """News feed for the LLM context layer (consumed in Phase 5)."""

    @abstractmethod
    async def get_news(self, symbol_or_index: str, since) -> list[dict]:
        ...
