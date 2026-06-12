"""Run the real FeedManager inside an asyncio loop for 60s and count processed
batches every 5s — to localize the stall in the asyncio bridge."""
from __future__ import annotations

import asyncio

from broker.kite_adapter import KiteAdapter
from config.loader import get_config
from config.settings import get_settings
from data.feed import FeedManager
from data.rate_governor import RateGovernor

TOKENS = [738561, 256265, 779521]


async def main() -> None:
    adapter = KiteAdapter(get_settings())
    adapter.ensure_token()
    gov = RateGovernor(get_config().data.rate_limits)
    feed = FeedManager(adapter, gov, TOKENS, ["1m", "5m"], mode="full", feed_cfg=get_config().data.feed)

    cnt = {"n": 0}
    orig = feed._process

    async def wrap(ticks):
        cnt["n"] += 1
        await orig(ticks)

    feed._process = wrap
    await feed.start()

    # Replicate the engine: start an AsyncIOScheduler alongside the feed.
    from apscheduler.triggers.cron import CronTrigger

    from broker.scheduler import build_scheduler
    from common.market_time import IST
    sched = build_scheduler()
    sched.add_job(lambda: None, CronTrigger(hour=8, minute=0, timezone=str(IST)), id="t")
    sched.start()
    print("scheduler started alongside feed", flush=True)

    for i in range(12):
        await asyncio.sleep(5)
        print(f"  t+{(i + 1) * 5:>2}s: processed_batches={cnt['n']}", flush=True)
    await feed.stop()
    print("RESULT:", cnt["n"], "batches in 60s ->",
          "STREAMING OK" if cnt["n"] > 10 else "STALLED")


if __name__ == "__main__":
    asyncio.run(main())
