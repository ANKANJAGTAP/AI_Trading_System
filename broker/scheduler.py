"""APScheduler factory.

Returns an (unstarted) AsyncIOScheduler anchored to IST. Jobs are added by the
engine so they can reference the market-data service. IMPORTANT: CronTrigger does
NOT inherit the scheduler's timezone — every CronTrigger must be given
`timezone=str(IST)` explicitly, or it defaults to UTC.
"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from common.market_time import IST


def build_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone=str(IST))
