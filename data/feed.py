"""Live market-data feed manager (spec §7).

Wraps KiteTicker (which runs its own background thread), marshals ticks onto the
asyncio loop, drives the CandleAggregator, persists closed candles immediately,
maintains live LTP state in Redis, detects staleness, and — on reconnect after a
drop — runs candle gap reconciliation (backfill the hole from the historical API)
before resuming. Decisions must not run on a known-incomplete series.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime

from common.logging import get_logger
from common.market_time import IST, is_within, now_ist
from common.redis_client import get_redis
from data.aggregator import CandleAggregator
from data.historical import reconcile_gap
from data.store import insert_ticks, upsert_candles

log = get_logger("feed")


def _ensure_ist(dt) -> datetime:
    if not isinstance(dt, datetime):
        return now_ist()
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)


def _normalize_tick(t: dict, ts: datetime) -> dict:
    depth = t.get("depth") or {}
    buy = depth.get("buy") or []
    sell = depth.get("sell") or []
    return {
        "ts": ts,
        "instrument_token": t["instrument_token"],
        "last_price": t.get("last_price"),
        "last_quantity": t.get("last_traded_quantity"),
        "average_price": t.get("average_traded_price"),
        "volume": t.get("volume_traded"),
        "buy_quantity": t.get("total_buy_quantity"),
        "sell_quantity": t.get("total_sell_quantity"),
        "oi": t.get("oi"),
        "bid": buy[0].get("price") if buy else None,
        "ask": sell[0].get("price") if sell else None,
        "raw": None,
    }


class FeedManager:
    def __init__(
        self,
        adapter,
        governor,
        tokens: list[int],
        intervals: list[str],
        mode: str = "full",
        archive_ticks: bool = False,
        oi_tokens: set[int] | None = None,
        max_days_per_request: dict | None = None,
        feed_cfg: dict | None = None,
        alerter=None,
    ) -> None:
        self.adapter = adapter
        self.governor = governor
        self.tokens = tokens
        self.mode = mode
        self.archive_ticks = archive_ticks
        self.oi_tokens = set(oi_tokens or [])
        self.max_days = max_days_per_request or {}
        self.cfg = feed_cfg or {}
        self.alerter = alerter

        self.aggregator = CandleAggregator(intervals)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ticker = None
        self.last_tick_monotonic: float | None = None
        self._had_disconnect = False
        self._stopped = False
        self._tasks: list[asyncio.Task] = []
        # self-heal: rebuild a stale feed during market hours (KiteTicker handles
        # transient drops itself; this backstops token-expiry / give-up cases).
        self._reconnect_after = float((self.cfg or {}).get("reconnect_after_stale_seconds", 60))
        self._market_window = (self.cfg or {}).get("market_window", ["09:15", "15:30"])
        self._last_reconnect_monotonic = 0.0
        self._reconnecting = False
        self._last_price_pub = 0.0
        # fast-loop hook: engine sets this to drive position guards per tick.
        self.on_ltp = None  # async callable(ltp_map: dict[str, float]) | None
        # fail-safe hook: engine sets this; fired once when staleness is prolonged
        # past reconnect (square off + halt rather than hold through an unknown state).
        self.on_failsafe = None  # async callable(reason: str) | None
        self._failsafe_after = float((self.cfg or {}).get("failsafe_after_stale_seconds", 180))
        self._failsafe_fired = False
        self._was_in_market = False   # tracks session transitions for the watchdog

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._build_ticker()
        self.ticker.connect(threaded=True)
        self._tasks = [
            asyncio.create_task(self._consume()),
            asyncio.create_task(self._watchdog()),
        ]
        log.info("feed_started", tokens=len(self.tokens), mode=self.mode)

    def _build_ticker(self) -> None:
        self.ticker = self.adapter.make_ticker()
        self.ticker.on_ticks = self._on_ticks
        self.ticker.on_connect = self._on_connect
        self.ticker.on_close = self._on_close
        self.ticker.on_error = self._on_error
        self.ticker.on_reconnect = self._on_reconnect
        self.ticker.on_noreconnect = self._on_noreconnect

    # --- KiteTicker thread callbacks (NOT on the asyncio loop) ------------
    def _on_ticks(self, ws, ticks) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ticks)

    def _on_connect(self, ws, response) -> None:
        log.info("feed_connected", reconnected=self._had_disconnect)
        mode_const = getattr(ws, f"MODE_{self.mode.upper()}", ws.MODE_FULL)
        ws.subscribe(self.tokens)
        ws.set_mode(mode_const, self.tokens)
        if self._had_disconnect and self.loop is not None:
            self.loop.call_soon_threadsafe(
                asyncio.create_task, self._reconcile_after_reconnect()
            )

    def _on_close(self, ws, code, reason) -> None:
        log.warning("feed_closed", code=code, reason=str(reason))

    def _on_error(self, ws, code, reason) -> None:
        log.error("feed_error", code=code, reason=str(reason))

    def _on_reconnect(self, ws, attempts) -> None:
        self._had_disconnect = True
        log.warning("feed_reconnecting", attempts=attempts)

    def _on_noreconnect(self, ws) -> None:
        log.error("feed_noreconnect")
        if self.alerter:
            self.alerter.send(
                "Market feed gave up reconnecting",
                "KiteTicker exhausted reconnect attempts; rebuilding with a fresh token.",
            )
        # KiteTicker gave up (often a stale token) — rebuild with a fresh token.
        if self.loop is not None:
            self.loop.call_soon_threadsafe(asyncio.create_task, self.reconnect())

    # --- asyncio side -----------------------------------------------------
    async def _consume(self) -> None:
        log.info("feed_consumer_started")
        while not self._stopped:
            ticks = await self.queue.get()
            self.last_tick_monotonic = time.monotonic()
            try:
                await self._process(ticks)
            except Exception as exc:
                log.error("tick_process_error", error=str(exc))

    async def _process(self, ticks: list[dict]) -> None:
        candle_rows: list[tuple] = []
        tick_rows: list[dict] = []
        ltp_map: dict[str, float] = {}
        for t in ticks:
            token = t.get("instrument_token")
            ltp = t.get("last_price")
            if token is None or ltp is None:
                continue
            ts = _ensure_ist(t.get("exchange_timestamp"))
            cum_vol = t.get("volume_traded") or 0
            oi = t.get("oi")
            for closed in self.aggregator.add_tick(token, ts, ltp, cum_vol, oi):
                candle_rows.append(closed.as_row())
            ltp_map[str(token)] = ltp
            if self.archive_ticks:
                tick_rows.append(_normalize_tick(t, ts))

        if candle_rows:
            await upsert_candles(candle_rows)
        if tick_rows:
            await insert_ticks(tick_rows)
        if ltp_map:
            redis = await get_redis()
            await redis.hset("md:ltp", mapping=ltp_map)
            await redis.set("aegis:feed:last_tick", now_ist().isoformat())  # dashboard health
            # throttled batched price_update for the dashboard Market grid + Ticker (~1/s)
            now_m = time.monotonic()
            if now_m - self._last_price_pub > 1.0:
                self._last_price_pub = now_m
                try:
                    from common.events import publish_event
                    await publish_event("price_update", {"ltps": ltp_map})
                except Exception:
                    pass
            if self.on_ltp is not None:  # fast loop: drive position guards
                try:
                    await self.on_ltp(ltp_map)
                except Exception as exc:
                    log.error("on_ltp_error", error=str(exc))

    async def _watchdog(self) -> None:
        heartbeat = float(self.cfg.get("heartbeat_seconds", 5))
        staleness = float(self.cfg.get("staleness_seconds", 30))
        log.info("feed_watchdog_started", heartbeat=heartbeat, staleness=staleness)
        cycles = 0
        every = max(1, int(30 / heartbeat))
        while not self._stopped:
            await asyncio.sleep(heartbeat)
            cycles += 1
            in_market = is_within(self._market_window[0], self._market_window[1])
            if not in_market:
                # Out of session: no ticks is EXPECTED (the exchange isn't trading).
                # Hold the staleness clock fresh and re-arm the one-shot failsafe so
                # accumulated overnight/pre-market idle can't trip reconnect/failsafe
                # the instant the market opens.
                self.last_tick_monotonic = time.monotonic()
                self._failsafe_fired = False
                if not self._was_in_market:
                    if cycles % every == 0:
                        log.info("feed_health", idle=0, queue=self.queue.qsize(), session="closed")
                    continue
                self._was_in_market = False
                continue
            if not self._was_in_market:
                # Market just opened: refresh the socket so ticks flow promptly, and
                # start the staleness clock from now.
                self._was_in_market = True
                self.last_tick_monotonic = time.monotonic()
                if not self._reconnecting:
                    log.info("market_open_feed_refresh")
                    asyncio.create_task(self.reconnect())
                continue
            idle = None if self.last_tick_monotonic is None else (time.monotonic() - self.last_tick_monotonic)
            if cycles % every == 0:  # periodic health heartbeat (~30s)
                log.info("feed_health", idle=None if idle is None else int(idle),
                         queue=self.queue.qsize(), reconnecting=self._reconnecting)
            if idle is None or idle <= staleness:
                continue
            log.warning("feed_stale", idle_seconds=int(idle))
            # In-session staleness -> self-heal (reconnect), then escalate to the
            # fail-safe (square off + halt) if it persists. Fired as tasks so a slow
            # reconnect can never block the watchdog.
            cooled = (time.monotonic() - self._last_reconnect_monotonic) > 120
            if idle > self._reconnect_after and cooled and not self._reconnecting:
                log.warning("feed_stale_triggering_reconnect", idle_seconds=int(idle))
                asyncio.create_task(self.reconnect())
            if idle > self._failsafe_after and self.on_failsafe is not None and not self._failsafe_fired:
                self._failsafe_fired = True
                log.error("feed_stale_triggering_failsafe", idle_seconds=int(idle))
                asyncio.create_task(self.on_failsafe(f"feed stale {int(idle)}s — no ticks"))

    async def _reconcile_after_reconnect(self) -> None:
        # Drop partial in-progress candles; the historical API is authoritative
        # for the gap. Backfill each token/interval before resuming decisions.
        self.aggregator.flush()
        for token in self.tokens:
            for interval in self.aggregator.intervals:
                if interval == "day":
                    continue
                try:
                    await reconcile_gap(
                        self.adapter, self.governor, token, interval,
                        max_days=int(self.max_days.get(interval, 60)),
                        oi=token in self.oi_tokens,
                    )
                except Exception as exc:
                    log.error("reconcile_failed", token=token, interval=interval, error=str(exc))
        self._had_disconnect = False
        log.info("gap_reconcile_complete")

    async def reconnect(self) -> None:
        """Rebuild the ticker with a fresh token (token expiry / KiteTicker gave up).
        on_connect will re-subscribe and trigger gap reconciliation."""
        if self._reconnecting:
            return
        self._reconnecting = True
        self._last_reconnect_monotonic = time.monotonic()
        try:
            log.warning("feed_reconnect_begin")
            try:
                if self.ticker is not None:
                    self.ticker.close()
            except Exception:
                pass
            self._had_disconnect = True  # so on_connect runs gap reconciliation
            # Ensure today's token before rebuilding the socket (blocking -> thread).
            await asyncio.to_thread(self.adapter.ensure_token)
            self._build_ticker()
            self.ticker.connect(threaded=True)
            self.last_tick_monotonic = time.monotonic()  # reset staleness clock
            log.info("feed_reconnect_done")
        except Exception as exc:
            log.error("feed_reconnect_failed", error=str(exc))
        finally:
            self._reconnecting = False

    async def stop(self) -> None:
        self._stopped = True
        try:
            if self.ticker is not None:
                self.ticker.close()
        except Exception:
            pass
        for task in self._tasks:
            task.cancel()
        log.info("feed_stopped")
