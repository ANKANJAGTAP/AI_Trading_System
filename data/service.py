"""Market-data service: orchestrates instruments master, historical backfill, and
the live feed. Started by the engine; also exposes scheduler jobs (daily
instruments refresh, nightly incremental backfill).
"""
from __future__ import annotations

from common.db import fetchval
from common.logging import get_logger
from data.feed import FeedManager
from data.historical import incremental_backfill
from data.instruments import refresh_instruments, resolve_tokens
from data.rate_governor import RateGovernor

log = get_logger("market_data")


class MarketDataService:
    def __init__(self, adapter, config, settings, alerter=None) -> None:
        self.adapter = adapter
        self.config = config
        self.settings = settings
        self.alerter = alerter
        self.governor = RateGovernor(config.data.rate_limits, alerter)
        self.feed: FeedManager | None = None
        self.tokens: list[int] = []
        self.oi_tokens: set[int] = set()
        self.on_ltp = None  # fast-loop hook; wired onto the feed when it starts
        self.on_failsafe = None  # async(reason) hook; fired on prolonged feed staleness

    def _feed_intervals(self) -> list[str]:
        # Daily candles come from EOD backfill, not the live aggregator.
        intervals = self.config.data.candles.get("intervals", ["1m", "5m", "15m"])
        return [i for i in intervals if i != "day"]

    async def ensure_instruments(self) -> int:
        count = await fetchval("SELECT count(*) FROM instruments")
        if not count:
            exchanges = (self.config.data.backfill or {}).get("instrument_exchanges")
            await refresh_instruments(self.adapter, self.governor, exchanges)
            count = await fetchval("SELECT count(*) FROM instruments")
        return count or 0

    async def resolve_universe(self) -> dict[str, int]:
        subs = (self.config.data.universe or {}).get("subscribe", [])
        token_map = await resolve_tokens(subs)
        self.tokens = list(token_map.values())
        # MCX: configured by NAME (contracts roll monthly) — resolve the live
        # front-month future per name, subscribe it, and track OI on it.
        self.mcx_front: dict[str, dict] = {}
        from data.instruments import front_month_future
        for name in (self.config.data.universe or {}).get("mcx_futures", []) or []:
            try:
                inst = await front_month_future(name)
                if inst:
                    self.mcx_front[name] = inst
                    tok = int(inst["instrument_token"])
                    if tok not in self.tokens:
                        self.tokens.append(tok)
                    self.oi_tokens.add(tok)
                else:
                    log.warning("mcx_front_month_unresolved", name=name)
            except Exception as exc:
                log.warning("mcx_front_month_error", name=name, error=str(exc))
        if self.mcx_front:
            log.info("mcx_universe_resolved",
                     contracts={n: i["tradingsymbol"] for n, i in self.mcx_front.items()})
        return token_map

    async def backfill_all(self) -> None:
        bf = self.config.data.backfill or {}
        intervals = bf.get("intervals", [])
        lookback = bf.get("lookback_days", {})
        max_days = bf.get("max_days_per_request", {})
        for token in self.tokens:
            for interval in intervals:
                try:
                    await incremental_backfill(
                        self.adapter, self.governor, token, interval,
                        int(lookback.get(interval, 30)), int(max_days.get(interval, 60)),
                        oi=token in self.oi_tokens,
                    )
                except Exception as exc:
                    log.error("backfill_error", token=token, interval=interval, error=str(exc))

    async def start(self, do_backfill: bool = True, start_feed: bool = True) -> None:
        count = await self.ensure_instruments()
        log.info("instruments_ready", count=count)
        await self.resolve_universe()
        log.info("universe_resolved", tokens=len(self.tokens))
        if do_backfill:
            await self.backfill_all()
        if start_feed:
            universe = self.config.data.universe or {}
            self.feed = FeedManager(
                adapter=self.adapter,
                governor=self.governor,
                tokens=self.tokens,
                intervals=self._feed_intervals(),
                mode=universe.get("tick_mode", "full"),
                archive_ticks=bool((self.config.data.feed or {}).get("archive_ticks", False)),
                oi_tokens=self.oi_tokens,
                max_days_per_request=(self.config.data.backfill or {}).get("max_days_per_request", {}),
                feed_cfg=self.config.data.feed,
                alerter=self.alerter,
            )
            self.feed.on_ltp = self.on_ltp
            self.feed.on_failsafe = self.on_failsafe
            await self.feed.start()
        log.info("market_data_started")

    # --- scheduler jobs ---
    async def refresh_instruments_job(self) -> None:
        exchanges = (self.config.data.backfill or {}).get("instrument_exchanges")
        await refresh_instruments(self.adapter, self.governor, exchanges)

    async def nightly_backfill_job(self) -> None:
        if not self.tokens:
            await self.resolve_universe()
        await self.backfill_all()

    async def snapshot_iv_job(self) -> None:
        """EOD: record each F&O underlying's ATM IV so per-name IV Rank can be built
        (Phase 2.2). Best-effort per name — a failure must not block others."""
        from data.iv_history import record_atm_iv
        from data.option_chain import atm_iv
        for e in (self.config.data.universe or {}).get("fno", []):
            name, ukey = e.get("name"), e.get("underlying")
            if not name or not ukey:
                continue
            try:
                iv = await atm_iv(self.adapter, self.governor, name, ukey)
                if iv and iv > 0:
                    await record_atm_iv(name, round(iv, 4))
            except Exception as exc:
                log.warning("iv_snapshot_failed", name=name, error=str(exc))
        log.info("iv_snapshot_complete")

    async def reconnect_feed(self) -> None:
        """Rebuild the live feed with the current token (after a daily refresh)."""
        if self.feed is not None:
            await self.feed.reconnect()

    async def stop(self) -> None:
        if self.feed is not None:
            await self.feed.stop()
