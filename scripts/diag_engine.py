"""Mirror the engine bootstrap (backfill -> feed via MarketDataService, scheduler,
background task) and watch whether the feed's tick clock advances or freezes."""
from __future__ import annotations

import asyncio

from apscheduler.triggers.cron import CronTrigger

from broker.kite_adapter import KiteAdapter
from broker.scheduler import build_scheduler
from common.db import close_pool, init_pool
from common.market_time import IST
from common.redis_client import close_redis, get_redis
from config.loader import get_config
from config.settings import get_settings
from data.service import MarketDataService


async def _safe(md):
    try:
        await md.start()
    except Exception as exc:
        print("md.start failed:", exc, flush=True)


async def main() -> None:
    cfg = get_config()
    s = get_settings()
    await init_pool()
    await get_redis()
    adapter = KiteAdapter(s)
    md = MarketDataService(adapter, cfg, s)

    asyncio.create_task(_safe(md))  # same as engine: background start (backfill+feed)

    sched = build_scheduler()
    hh, mm = cfg.system.token_refresh_time.split(":")
    sched.add_job(lambda: None, CronTrigger(hour=int(hh), minute=int(mm), timezone=str(IST)), id="tr")
    sched.add_job(md.refresh_instruments_job, CronTrigger(hour=8, minute=15, timezone=str(IST)), id="ir")
    sched.add_job(md.nightly_backfill_job, CronTrigger(hour=16, minute=0, timezone=str(IST)), id="nb")
    sched.start()

    prev = None
    for i in range(16):
        await asyncio.sleep(5)
        fb = md.feed
        lt = round(fb.last_tick_monotonic, 1) if (fb and fb.last_tick_monotonic) else None
        moving = (lt is not None and lt != prev)
        prev = lt
        print(f"t+{(i + 1) * 5:>2}s: feed={'Y' if fb else 'N'} last_tick={lt} advancing={moving}", flush=True)

    sched.shutdown(wait=False)
    await md.stop()
    await close_pool()
    await close_redis()


if __name__ == "__main__":
    asyncio.run(main())
