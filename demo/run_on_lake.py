"""
Run the platform on the REAL lake (Kite-captured data) instead of synthetic.

Run on the server, where the lake lives:
    python -m demo.run_on_lake --underlying NIFTY --start 2026-06-01 --end 2026-06-15

It reports, in order of how much history each stage needs:
  * lake summary,
  * the underlying daily series (from futures, or put-call parity if none),
  * REAL per-day option analytics (PCR / ATM-IV / net-GEX / max-pain / skew) —
    these are meaningful from day one,
  * TA features + CPCV validation — gated on having enough trading days, since
    20-period indicators and labelling need a few weeks. With a thin lake these
    print a "needs more history" note and fill in as forward-capture accumulates.
"""
from __future__ import annotations

import argparse
import datetime as dt

import pandas as pd

from dataplatform.storage import ParquetLake
from features.engine import underlying_daily_from_eod, option_features_timeseries, FeatureEngine
from ml.pipeline import make_events, label_events, build_dataset, evaluate_cpcv

TA_FEATURES = ["ema_20", "rsi_14", "atr_pct_14", "macd_hist", "rvol_20", "bb_pctb_20"]


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def run(underlying: str, start: dt.date, end: dt.date, lake: ParquetLake | None = None) -> dict:
    lake = lake or ParquetLake()
    eod = lake.read_eod(underlying=underlying, start=start, end=end)
    bar = "=" * 70
    print(bar)
    print(f" REAL-LAKE RUN — {underlying}   {start} -> {end}")
    print(bar)
    if eod.empty:
        print(f"No data in the lake for {underlying} {start}..{end}. Backfill first "
              f"(python -m dataplatform.pull_kite_data ...).")
        return {"rows": 0}

    n_days = eod["trade_date"].nunique()
    fut = int((eod["instrument"] == "FUT").sum())
    opt = int((eod["instrument"] == "OPT").sum())
    print(f"[lake]      {len(eod):,} rows · {n_days} trading days · FUT={fut} OPT={opt}")

    # underlying daily series
    daily = underlying_daily_from_eod(eod, underlying)
    src = "futures" if fut > 0 else "option put-call parity"
    tail = f" · last close={daily['close'].iloc[-1]:.1f}" if len(daily) else ""
    print(f"[underlying] {len(daily)} daily closes (from {src}){tail}")

    # REAL options analytics — useful immediately
    of = option_features_timeseries(eod, underlying)
    if not of.empty:
        print(f"[options]   per-day analytics — last {min(len(of), 8)} of {len(of)} days:")
        cols = [c for c in ["pcr_oi", "atm_iv", "net_gex", "max_pain", "skew"] if c in of.columns]
        print(of[cols].round(3).tail(8).to_string())
    else:
        print("[options]   no option-chain features computed")

    # TA features (gated on warmup)
    ta = FeatureEngine(TA_FEATURES).compute(daily) if len(daily) else pd.DataFrame()
    usable = int(ta.dropna(how="any").shape[0]) if len(ta) else 0
    note = "" if usable else "  (need ~20+ trading days for the 20-period features)"
    print(f"[features]  {len(TA_FEATURES)} TA features · {usable} fully-populated rows{note}")

    # labels + CPCV (gated on enough events)
    cpcv = None
    if len(daily) >= 30 and usable >= 30:
        events = make_events(daily["close"], vol_span=10, vertical_bars=5)
        barrier = label_events(daily["close"], events, (1.5, 1.5))
        X, y, t1 = build_dataset(ta, barrier)
        if len(X) >= 30:
            cpcv = evaluate_cpcv(X, y, t1, n_groups=6, n_test_groups=2)
            print(f"[validation] CPCV mean acc={cpcv['mean']:.3f} · "
                  f"{cpcv['n_splits_used']} splits · {cpcv['n_paths']} paths")
        else:
            print(f"[validation] only {len(X)} labelled rows — need more history for CPCV")
    else:
        print(f"[validation] {n_days} days — need ~30+ for labelling/CPCV (skipped)")

    print(bar)
    print("Real option analytics are live above. TA/ML/backtest fill in as the")
    print("forward-capture lake grows (or after a bulk historical pull).")
    print(bar)
    return {"rows": len(eod), "days": n_days, "options_days": len(of),
            "ta_usable_rows": usable, "cpcv": cpcv}


def main(argv=None):
    p = argparse.ArgumentParser(prog="run_on_lake")
    p.add_argument("--underlying", default="NIFTY")
    p.add_argument("--start", required=True, type=_date)
    p.add_argument("--end", required=True, type=_date)
    a = p.parse_args(argv)
    run(a.underlying, a.start, a.end)


if __name__ == "__main__":
    main()
