"""CLI: run an intraday backtest from the terminal (no API needed).

Usage:
    python scripts/backtest.py --symbols NSE:RELIANCE NSE:TCS --from 2024-01-01 --to 2024-03-31
    python scripts/backtest.py --symbols NSE:RELIANCE --from 2024-01-01 --to 2024-03-31 --capital 1000000 --risk 1.0
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date

# This file is named backtest.py, which would otherwise shadow the top-level
# `backtest/` package (the script's own dir lands first on sys.path). Put the repo
# root first so `import backtest.engine` resolves to the package, not this file.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import BacktestParams, run_backtest  # noqa: E402
from common.db import close_pool, init_pool
from common.logging import configure_logging


async def _main(args) -> None:
    configure_logging()
    await init_pool()
    try:
        params = BacktestParams(
            symbols=args.symbols, from_dt=date.fromisoformat(args.from_date),
            to_dt=date.fromisoformat(args.to_date), sleeve=args.sleeve,
            starting_capital=args.capital, per_trade_pct=args.risk)
        if args.walkforward and args.walkforward >= 2:
            from backtest.walkforward import walk_forward
            wf = await walk_forward(params, folds=args.walkforward)
            if wf.get("error"):
                print("ERROR:", wf["error"]); return
            print(f"\n=== Walk-forward ({args.walkforward} folds) {args.from_date}..{args.to_date} ===")
            print(f"{'fold':<5}{'period':<26}{'trades':>7}{'exp_R':>8}{'win%':>7}{'PF':>6}")
            for f in wf["folds"]:
                print(f"{f['fold']:<5}{f['from']+'..'+f['to']:<26}{f['trades']:>7}{f['expectancy_R']:>8}{f['win_rate']:>7}{f['profit_factor']:>6}")
            s = wf["summary"]
            print(f"\nfolds positive: {s['folds_positive']}/{s['folds_evaluated']}  "
                  f"mean exp {s['mean_expectancy_R']}R (sd {s['expectancy_stdev']})  "
                  f"VERDICT: {s['verdict']}")
            return
        result = await run_backtest(params)
        m = result["metrics"]
        if result.get("error"):
            print("ERROR:", result["error"])
            return
        print(f"\n=== Backtest {args.sleeve}  {args.from_date} .. {args.to_date} ===")
        print(f"symbols   : {', '.join(args.symbols)}")
        if result.get("skipped"):
            print(f"skipped   : {', '.join(result['skipped'])} (no candles / unresolved)")
        print(f"trades    : {m['trades']}")
        print(f"net P&L   : Rs {m['net_pnl']:,.0f}  ({m['return_pct']}% of capital)")
        print(f"win rate  : {m['win_rate']}%")
        print(f"expectancy: {m['expectancy_R']} R")
        print(f"profit f. : {m['profit_factor']}")
        print(f"max DD    : Rs {m['max_dd']:,.0f}")
        print(f"sharpe    : {m['sharpe']}")
        print(f"largest   : +Rs {m['largest_win']:,.0f} / -Rs {abs(m['largest_loss']):,.0f}")
        disc = result.get("discrimination")
        if disc:
            print(f"\n--- feature discrimination (verdict: {disc['verdict']}, n={disc['n_samples']}) ---")
            varying = [f for f in disc["features"] if f.get("win_rate_high") is not None]
            if not varying:
                print("    all features constant -> no discriminating signal")
            for f in varying[:8]:
                flag = "  <-- signal" if abs(f["lift"]) >= 0.15 else ""
                print(f"    {f['feature']:<16} win% hi={round(f['win_rate_high']*100):>3} "
                      f"lo={round(f['win_rate_low']*100):>3}  lift={f['lift']:+.2f}{flag}")
    finally:
        await close_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", nargs="+", required=True, help="EXCHANGE:TRADINGSYMBOL ...")
    p.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--sleeve", default="intraday_stocks")
    p.add_argument("--capital", type=float, default=1_000_000.0)
    p.add_argument("--risk", type=float, default=1.0, help="per-trade risk %")
    p.add_argument("--walkforward", type=int, default=0, help="N time folds for walk-forward validation")
    asyncio.run(_main(p.parse_args()))
