"""Offline overfitting-validation sweep for the F&O (option-chain) strategy.

Runs the fno_signals decision engine over the REAL bhavcopy chains in the lake
across a grid of one SIGNAL parameter (e.g. `gate.max_dte`), collects each
config's per-trade P&L, and feeds `report_from_results` (Deflated Sharpe + PBO)
for an honest "real edge vs curve-fit" verdict. The expensive feature matrices are
computed ONCE and reused across configs. Runs in its own process — never the API
web worker (heavy backtests there starve /health).

    sudo docker compose exec -T api python scripts/fno_sweep.py \
        --underlying NIFTY --from 2023-06-20 --to 2026-06-20 --capital 5000000 \
        --param gate.max_dte --values 7,15,30,45

Good signal axes (each changes WHICH trades are taken -> a non-degenerate PBO):
  gate.max_dte  7,15,30,45        (expiry window)
  gate.min_atm_oi  2000,5000,10000,20000   (liquidity floor)
  width_steps  1,2,3              (spread width)
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---- pure helpers (stdlib only -> unit-testable) -----------------------------
def coerce_value(s):
    """'30'->30, '0.5'->0.5, 'true'->True, else str. Pure."""
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
    """One dotted DecisionConfig path + values -> sweep configs. Pure.

    e.g. build_grid('gate.max_dte', ['7','30']) ->
         [{'label':'max_dte=7','path':'gate.max_dte','value':7}, ...].
    """
    leaf = param.split(".")[-1]
    out = []
    for v in values:
        if v == "" or v is None:
            continue
        out.append({"label": f"{leaf}={v}", "path": param, "value": coerce_value(v)})
    return out


def set_decision_param(dcfg, path: str, value):
    """Deep-copy a DecisionConfig and set a dotted attr (e.g. 'gate.max_dte'). Pure.

    Raises AttributeError if the path doesn't exist (so a typo fails loudly rather
    than silently creating a dead attribute)."""
    cfg = copy.deepcopy(dcfg)
    obj = cfg
    parts = path.split(".")
    for p in parts[:-1]:
        obj = getattr(obj, p)
    if not hasattr(obj, parts[-1]):
        raise AttributeError(f"DecisionConfig has no attribute path '{path}'")
    setattr(obj, parts[-1], value)
    return cfg


def trades_to_returns_rows(records) -> list[dict]:
    """fno_backtest trade records -> [{ts, pnl}] for report_from_results. Pure.

    `entry_date` is the bucketing day; `net` is the post-cost P&L."""
    out = []
    for r in records:
        ts = r.get("entry_date")
        out.append({"ts": str(ts)[:10] if ts is not None else "",
                    "pnl": float(r.get("net", 0.0) or 0.0)})
    return out


# ---- offline runner (heavy imports deferred) --------------------------------
def _run(args) -> int:
    import pandas as pd
    from dataplatform.storage import ParquetLake
    from dataplatform.contracts import ContractSpecResolver
    from features.engine import build_feature_matrix, option_features_timeseries
    from fno_backtest.engine import backtest_strategy
    from fno_signals import DecisionConfig, MarketContext, RiskState, SizingConfig, decide
    from backtest.sweep import report_from_results
    from api.fno_lake import TA_FEATURES, _rolling_iv_rank

    try:
        start, end = dt.date.fromisoformat(args.from_date), dt.date.fromisoformat(args.to_date)
    except ValueError:
        print("ERROR: --from/--to must be YYYY-MM-DD")
        return 2
    configs = build_grid(args.param, args.values.split(","))
    if len(configs) < 2:
        print("ERROR: need >= 2 values to sweep (PBO compares configs)")
        return 2

    eod = ParquetLake().read_eod(underlying=args.underlying, start=start, end=end)
    if len(eod) == 0:
        print(f"ERROR: no lake data for {args.underlying} in {start}..{end}")
        return 1

    # config-independent — compute once, reuse for every config
    lot_size = int(ContractSpecResolver().lot_size(args.underlying, end))
    fmat = build_feature_matrix(eod, args.underlying, feature_ids=TA_FEATURES)
    opt_feats = option_features_timeseries(eod, args.underlying)
    iv_rank = _rolling_iv_rank(opt_feats["atm_iv"]) if not opt_feats.empty else pd.Series(dtype=float)
    base = DecisionConfig(sizing=SizingConfig(capital=args.capital,
                                              per_trade_risk_pct=args.per_trade_pct))

    def make_strategy(dcfg, risk_state):
        def strategy(date, chain, spot):
            if date not in fmat.index:
                return None
            feats = fmat.loc[date].to_dict()
            if any(pd.isna(feats.get(c)) for c in TA_FEATURES):
                return None                                     # warmup not satisfied
            ivr = iv_rank.get(date, 50.0)
            ivr = 50.0 if pd.isna(ivr) else float(ivr)
            atm = opt_feats["atm_iv"].get(date, 0.18) if not opt_feats.empty else 0.18
            atm = 0.18 if (pd.isna(atm) or atm <= 0) else float(atm)
            expiry = pd.Timestamp(chain["expiry"].iloc[0])
            ctx = MarketContext(
                args.underlying, date, float(spot), feats, ivr, atm,
                chain[["opt_type", "strike", "close", "oi", "volume"]],
                dte=max((expiry - date).days, 1), expiry=expiry, lot_size=lot_size, step=50.0)
            d = decide(ctx, dcfg, risk_state, meta_confidence=None)
            return d.structure if d.accepted else None
        return strategy

    print(f"fno sweep: {args.underlying}  {start}..{end}  capital={args.capital:,.0f}  "
          f"param={args.param}  configs={len(configs)}")
    results: dict[str, dict] = {}
    for c in configs:
        dcfg = set_decision_param(base, c["path"], c["value"])
        res = backtest_strategy(eod, args.underlying, make_strategy(dcfg, RiskState(capital=args.capital)),
                                starting_capital=args.capital)
        recs = res.trades.to_dict("records") if len(res.trades) else []
        rows = trades_to_returns_rows(recs)
        results[c["label"]] = {"trades": rows}
        net = sum(r["pnl"] for r in rows)
        print(f"[done] {c['label']:22s} trades={len(rows):4d} net={net:>13.0f}")

    report = report_from_results(results, args.capital, n_splits=args.n_splits)
    report["trades_per_config"] = {k: len(v["trades"]) for k, v in results.items()}
    report["param"] = args.param

    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"fno_sweep_{args.underlying}_{args.param.replace('.', '_')}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print("\n=== verdict ===")
    for k in ("configs", "periods", "best_config", "best_sharpe", "best_psr",
              "deflated_sharpe", "pbo", "verdict", "trades_per_config"):
        print(f"  {k}: {report.get(k)}")
    print(f"saved: {out}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--underlying", default="NIFTY")
    p.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--capital", type=float, default=5_000_000.0)
    p.add_argument("--per-trade-pct", dest="per_trade_pct", type=float, default=1.0)
    p.add_argument("--param", default="gate.max_dte",
                   help="dotted DecisionConfig path, e.g. gate.max_dte / gate.min_atm_oi / width_steps")
    p.add_argument("--values", default="7,15,30,45", help="comma-separated values for --param")
    p.add_argument("--n-splits", dest="n_splits", type=int, default=10)
    p.add_argument("--out-dir", default="backtest_sweeps")
    raise SystemExit(_run(p.parse_args()))


if __name__ == "__main__":
    main()
