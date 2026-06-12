"""Running equity curve & projection (CLI).

Prints the same report that the engine emails after close each day: starting from
a base capital (default: config risk.paper_capital = ₹10L), it rolls each trading
day's realized P&L into a running balance and projects ~1 month ahead. Read-only.
The report logic lives in common.equity_report (shared with the daily EOD email).

Usage:
    python -m scripts.equity_curve                       # base = paper_capital, 1-month horizon
    python -m scripts.equity_curve --capital 1000000 --days 21
"""
from __future__ import annotations

import argparse
import asyncio

from common.db import close_pool, init_pool
from common.equity_report import TRADING_DAYS_PER_MONTH, build_equity_report
from common.logging import configure_logging


async def main() -> None:
    ap = argparse.ArgumentParser(description="Running equity curve and projection.")
    ap.add_argument("--capital", type=float, default=None,
                    help="Starting capital (default: config risk.paper_capital, e.g. 1000000).")
    ap.add_argument("--days", type=int, default=TRADING_DAYS_PER_MONTH,
                    help="Projection horizon in trading days (default: 21 ≈ 1 month).")
    args = ap.parse_args()

    configure_logging()
    await init_pool()
    try:
        rep = await build_equity_report(start_capital=args.capital, horizon_days=args.days)
        print("\n" + rep.text)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
