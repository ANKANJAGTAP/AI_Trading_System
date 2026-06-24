"""Run a backtest sweep OFFLINE (in its own process), with the overfitting verdict
AND a gross-vs-net cost decomposition per config.

Heavy sweeps are CPU-bound and must NOT go through the API request path — a full
multi-symbol, multi-config, year-long intraday sweep pegs the single web worker and
starves /health. This CLI runs the exact same logic (`run_backtest` +
`report_from_results`) in a standalone process, so the API stays responsive.

    # sweep a SIGNAL parameter (non-degenerate -> PBO is meaningful):
    python scripts/run_sweep.py --from 2025-07-01 --to 2026-06-20 \
        --param strategy.intraday_stocks.regime.adx_trend_min --values 15,20,25,30

    # arbitrary grid via a JSON file of [{"label":..,"overrides":{path:val}}, ...]:
    python scripts/run_sweep.py --from 2025-07-01 --to 2026-06-20 --config-json grid.json

Run it inside the api container (DB + config + env already present):
    sudo docker compose exec -T api python scripts/run_sweep.py --from ... --to ... --param ... --values ...

Output: a per-config table (trades / gross / fees / net / win%), the verdict block
(Deflated Sharpe + PBO), and the full JSON saved under --out-dir. `gross_pnl` vs
`net_pnl` tells you whether a losing result is cost/overtrading drag (gross ~flat or
positive) or a genuine lack of signal edge (gross also negative).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---- pure helpers (no DB / engine imports -> unit-testable) -----------------
def coerce_value(s):
    """'20'->20, '1.5'->1.5, 'true'->True, '15:20'->'15:20'. Pure."""
    s = str(s).strip()
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    return s


def build_grid(param: str, values) -> list[dict]:
    """One swept dotted-path param + a list of values -> sweep configs.

    e.g. build_grid('a.b.adx_trend_min', ['15','20']) ->
         [{'label':'adx_trend_min=15','overrides':{'a.b.adx_trend_min':15}}, ...]. Pure.
    """
    leaf = param.split(".")[-1]
    out = []
    for v in values:
        if v == "" or v is None:
            continue
        out.append({"label": f"{leaf}={v}", "overrides": {param: coerce_value(v)}})
    return out


def summarize_config(res: dict) -> dict:
    """Per-config gross/net decomposition from a backtest result. Pure.

    `pnl` on each trade is NET of fees (engine: gross - entry_fees - exit_fees) and
    `fees` is the round-trip cost, so gross = net + fees.
    """
    trades = res.get("trades") or []
    n = len(trades)
    net = round(sum(float(t.get("pnl", 0) or 0) for t in trades), 2)
    fees = round(sum(float(t.get("fees", 0) or 0) for t in trades), 2)
    wins = sum(1 for t in trades if float(t.get("pnl", 0) or 0) > 0)
    m = res.get("metrics") or {}
    return {
        "trades": n,
        "gross_pnl": round(net + fees, 2),
        "fees": fees,
        "net_pnl": net,
        "net_per_trade": round(net / n, 2) if n else 0.0,
        "fees_per_trade": round(fees / n, 2) if n else 0.0,
        "win_rate_pct": round(wins / n * 100, 1) if n else 0.0,
        "sharpe": m.get("sharpe"),
        "expectancy_R": m.get("expectancy_R"),
        "max_drawdown": m.get("max_drawdown", m.get("max_dd")),
    }


# ---- offline runner (heavy imports deferred to here) ------------------------
async def _run(args) -> int:
    from common.db import close_pool, init_pool
    from config.loader import get_config
    from backtest.engine import BacktestParams, run_backtest
    from backtest.sweep import report_from_results
    from backtest.provenance import config_fingerprint
    from api.backtest import _apply_cfg_overrides

    if args.config_json:
        with open(args.config_json, encoding="utf-8") as fh:
            configs = json.load(fh)
    elif args.param and args.values:
        configs = build_grid(args.param, args.values.split(","))
    else:
        print("ERROR: pass --param PATH --values v1,v2,...  (or --config-json FILE)")
        return 2
    if len(configs) < 2:
        print("ERROR: a sweep needs at least 2 configs")
        return 2

    try:
        from_dt, to_dt = date.fromisoformat(args.from_date), date.fromisoformat(args.to_date)
    except ValueError:
        print("ERROR: --from/--to must be YYYY-MM-DD")
        return 2

    base = get_config()
    params = BacktestParams(symbols=args.symbols, from_dt=from_dt, to_dt=to_dt,
                            sleeve=args.sleeve, starting_capital=args.capital,
                            per_trade_pct=args.per_trade_pct)

    print(f"sweep: sleeve={args.sleeve} symbols={len(args.symbols)} "
          f"window={args.from_date}..{args.to_date} configs={len(configs)}")
    results: dict[str, dict] = {}
    await init_pool()
    try:
        seen: set[str] = set()
        for i, c in enumerate(configs):
            label = str(c.get("label") or f"cfg{i + 1}")
            if label in seen:
                label = f"{label}#{i + 1}"
            seen.add(label)
            try:
                cfg = _apply_cfg_overrides(base, c.get("overrides") or {})
            except Exception as exc:  # noqa: BLE001
                print(f"ERROR: bad overrides for '{label}': {exc}")
                return 2
            res = await run_backtest(params, cfg)
            if res.get("error"):
                print(f"ERROR: config '{label}': {res['error']}")
                return 1
            results[label] = res
            s = summarize_config(res)
            print(f"[done] {label:26s} trades={s['trades']:6d} "
                  f"net={s['net_pnl']:>13.0f} gross={s['gross_pnl']:>13.0f} "
                  f"fees={s['fees']:>11.0f} win%={s['win_rate_pct']:5.1f}")
    finally:
        await close_pool()

    report = report_from_results(results, args.capital, n_splits=args.n_splits)
    report["trades_per_config"] = {k: len(v.get("trades", [])) for k, v in results.items()}
    report["per_config"] = {k: summarize_config(v) for k, v in results.items()}
    report["config_fingerprint"] = config_fingerprint(base.model_dump())

    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir,
                       f"sweep_{args.sleeve}_{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    print("\n=== verdict ===")
    for k in ("periods", "best_config", "best_sharpe", "best_psr",
              "deflated_sharpe", "pbo", "verdict"):
        print(f"  {k}: {report.get(k)}")
    print(f"saved: {out}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sleeve", default="intraday_stocks", help="intraday_stocks | swing_stocks | fno")
    p.add_argument("--symbols", nargs="+",
                   default=["NSE:RELIANCE", "NSE:TCS", "NSE:INFY", "NSE:HDFCBANK", "NSE:ICICIBANK",
                            "NSE:SBIN", "NSE:LT", "NSE:ITC", "NSE:AXISBANK", "NSE:KOTAKBANK"])
    p.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--param", help="dotted config path to sweep, e.g. "
                                   "strategy.intraday_stocks.regime.adx_trend_min")
    p.add_argument("--values", help="comma-separated values for --param, e.g. 15,20,25,30")
    p.add_argument("--config-json", help="JSON file: explicit [{label,overrides}] list")
    p.add_argument("--capital", type=float, default=1_000_000.0)
    p.add_argument("--per-trade-pct", dest="per_trade_pct", type=float, default=1.0)
    p.add_argument("--n-splits", dest="n_splits", type=int, default=10)
    p.add_argument("--out-dir", default="backtest_sweeps", help="where to save the result JSON")
    raise SystemExit(asyncio.run(_run(p.parse_args())))


if __name__ == "__main__":
    main()
