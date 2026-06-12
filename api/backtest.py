"""Backtest API service: kick off a run (background task), persist runs + trades,
and read them back for the Research screen.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

from common.db import execute, fetch, fetchrow
from common.logging import get_logger
from common.market_time import now_ist
from backtest.engine import BacktestParams, run_backtest

log = get_logger("api_backtest")


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


async def start_run(sleeve: str, symbols: list[str], from_date: str, to_date: str,
                    starting_capital: float, per_trade_pct: float) -> dict:
    if not symbols:
        return {"error": "no symbols"}
    try:
        from_dt, to_dt = _parse_date(from_date), _parse_date(to_date)
    except Exception:
        return {"error": "from_date/to_date must be YYYY-MM-DD"}
    if from_dt >= to_dt:
        return {"error": "from_date must be before to_date"}

    row = await fetchrow(
        "INSERT INTO backtest_runs (sleeve, symbols, from_dt, to_dt, params, status) "
        "VALUES ($1,$2,$3,$4,$5::jsonb,'running') RETURNING id",
        sleeve, symbols, from_dt, to_dt,
        json.dumps({"starting_capital": starting_capital, "per_trade_pct": per_trade_pct}))
    run_id = row["id"]
    params = BacktestParams(symbols=symbols, from_dt=from_dt, to_dt=to_dt, sleeve=sleeve,
                            starting_capital=starting_capital, per_trade_pct=per_trade_pct)
    asyncio.create_task(_execute(run_id, params))
    return {"id": run_id, "status": "running"}


async def _execute(run_id: int, params: BacktestParams) -> None:
    try:
        result = await run_backtest(params)
        if result.get("error"):
            await execute("UPDATE backtest_runs SET status='error', error=$2, finished_at=now() WHERE id=$1",
                          run_id, result["error"])
            return
        for t in result["trades"]:
            await execute(
                "INSERT INTO backtest_trades (run_id, ts, symbol, sleeve, setup, side, entry, exit, "
                "quantity, pnl, r_multiple, fees, reason) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
                run_id, t["ts"], t["symbol"], t["sleeve"], t["setup"], t["side"], t["entry"],
                t["exit"], t["qty"], t["pnl"], t.get("r_multiple"), t["fees"], t["reason"])
        await execute("UPDATE backtest_runs SET status='done', metrics=$2::jsonb, finished_at=now() WHERE id=$1",
                      run_id, json.dumps(result["metrics"]))
        log.info("backtest_run_done", run_id=run_id, trades=len(result["trades"]))
    except Exception as exc:
        log.error("backtest_run_failed", run_id=run_id, error=str(exc))
        await execute("UPDATE backtest_runs SET status='error', error=$2, finished_at=now() WHERE id=$1",
                      run_id, str(exc))


async def get_run(run_id: int) -> dict:
    run = await fetchrow("SELECT * FROM backtest_runs WHERE id=$1", run_id)
    if not run:
        return {"error": "not found"}
    metrics = run["metrics"]
    if isinstance(metrics, str):
        metrics = json.loads(metrics)
    trades = await fetch("SELECT ts, symbol, setup, side, entry, exit, quantity, pnl, r_multiple, reason "
                         "FROM backtest_trades WHERE run_id=$1 ORDER BY ts", run_id)
    return {
        "id": run["id"], "status": run["status"], "sleeve": run["sleeve"],
        "symbols": list(run["symbols"] or []), "from": str(run["from_dt"]), "to": str(run["to_dt"]),
        "created_at": run["created_at"].isoformat() if run["created_at"] else None,
        "error": run["error"], "metrics": metrics or {},
        "trades": [{"ts": t["ts"].isoformat() if t["ts"] else None, "symbol": t["symbol"],
                    "setup": t["setup"], "side": t["side"], "entry": float(t["entry"] or 0),
                    "exit": float(t["exit"] or 0), "qty": int(t["quantity"] or 0),
                    "pnl": float(t["pnl"] or 0), "r_multiple": float(t["r_multiple"] or 0),
                    "reason": t["reason"]} for t in trades],
    }


async def list_runs(limit: int = 50) -> list[dict]:
    rows = await fetch("SELECT id, created_at, sleeve, symbols, from_dt, to_dt, status, metrics "
                       "FROM backtest_runs ORDER BY created_at DESC LIMIT $1", int(limit))
    out = []
    for r in rows:
        m = r["metrics"]
        if isinstance(m, str):
            m = json.loads(m)
        out.append({"id": r["id"], "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "sleeve": r["sleeve"], "symbols": list(r["symbols"] or []),
                    "from": str(r["from_dt"]), "to": str(r["to_dt"]), "status": r["status"],
                    "net_pnl": (m or {}).get("net_pnl"), "trades": (m or {}).get("trades"),
                    "win_rate": (m or {}).get("win_rate"), "expectancy_R": (m or {}).get("expectancy_R")})
    return out
