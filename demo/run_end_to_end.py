"""
End-to-end demo: chain all five pillars on synthetic data in one run.

    ingest (P1) -> features (P2) -> label + CPCV-validate (P3)
    -> signal-engine-driven backtest (P5) over the options-aware engine (P4)
    -> one consolidated report.

This is integration glue, not a strategy recommendation: it runs on SYNTHETIC
prices so the numbers are meaningless — its job is to prove the packages fit
together and to be the template you point at real vendor data later.

    python -m demo.run_end_to_end
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from dataplatform.vendors import SyntheticEODAdapter
from dataplatform.contracts import ContractSpecResolver
from features.engine import (
    build_feature_matrix, underlying_daily_from_eod, option_features_timeseries,
)
from ml.pipeline import make_events, label_events, build_dataset, evaluate_cpcv
from ml.models import LogisticMetaModel
from fno_backtest.engine import backtest_strategy
from fno_signals import MarketContext, DecisionConfig, SizingConfig, RiskState, decide

# short-lookback TA features (so the demo needs only a few months of history)
TA_FEATURES = ["ema_20", "rsi_14", "atr_pct_14", "macd_hist", "adx_14",
               "rvol_20", "bb_pctb_20", "supertrend_dir"]


def _rolling_iv_rank(atm_iv: pd.Series, window: int = 40) -> pd.Series:
    def rank(x):
        lo, hi = np.nanmin(x), np.nanmax(x)
        return (x[-1] - lo) / (hi - lo) * 100 if hi > lo else 50.0
    return atm_iv.rolling(window, min_periods=10).apply(rank, raw=True)


def run_demo(underlying: str = "NIFTY", start: dt.date = dt.date(2025, 11, 3),
             end: dt.date = dt.date(2026, 5, 29), capital: float = 1_000_000.0) -> dict:
    out = {"underlying": underlying}

    # ── [P1] ingest synthetic EOD F&O ───────────────────────────────────
    adapter = SyntheticEODAdapter()
    days = pd.bdate_range(start, end)
    eod = pd.concat([adapter.fetch_eod_fno(d.date()) for d in days], ignore_index=True)
    lot_size = ContractSpecResolver().lot_size(underlying, end)
    out["ingest"] = {"rows": len(eod), "days": len(days), "lot_size": lot_size}

    # ── [P2] features ───────────────────────────────────────────────────
    fmat = build_feature_matrix(eod, underlying, feature_ids=TA_FEATURES)
    daily = underlying_daily_from_eod(eod, underlying)
    opt_feats = option_features_timeseries(eod, underlying)
    iv_rank = _rolling_iv_rank(opt_feats["atm_iv"]) if not opt_feats.empty else pd.Series(dtype=float)
    out["features"] = {"observations": len(fmat),
                       "feature_columns": [c for c in fmat.columns if c in TA_FEATURES]}

    # ── [P3] triple-barrier labels + CPCV validation + meta-model ───────
    events = make_events(daily["close"], vol_span=20, vertical_bars=10)
    barrier = label_events(daily["close"], events, pt_sl=(1.5, 1.5))
    X, y, t1 = build_dataset(fmat[TA_FEATURES], barrier)
    cpcv = evaluate_cpcv(X, y, t1, n_groups=6, n_test_groups=2, embargo_pct=0.01)
    model = LogisticMetaModel(n_iter=1500).fit(X.to_numpy(), y.to_numpy()) if len(X) > 30 else None
    out["validation"] = {
        "labelled_events": len(X),
        "cpcv_mean_accuracy": cpcv["mean"],
        "cpcv_pct_folds_above_half": cpcv["pct_above_half"],
        "cpcv_paths": cpcv["n_paths"],
    }

    # ── [P5 over P4] signal-engine-driven backtest ──────────────────────
    dcfg = DecisionConfig(sizing=SizingConfig(capital=capital, per_trade_risk_pct=1.0))
    risk_state = RiskState(capital=capital)
    accepted = {"n": 0}
    rejects: dict[str, int] = {}

    def strategy(date, chain, spot):
        if date.weekday() != 0:                       # weekly cadence (Mondays)
            return None
        if date not in fmat.index:
            return None
        feats = fmat.loc[date].to_dict()
        if any(pd.isna(v) for v in (feats.get(c) for c in TA_FEATURES)):
            return None
        ivr = iv_rank.get(date, 50.0)
        ivr = 50.0 if pd.isna(ivr) else float(ivr)
        atm = opt_feats["atm_iv"].get(date, 0.18) if not opt_feats.empty else 0.18
        atm = 0.18 if (pd.isna(atm) or atm <= 0) else float(atm)
        expiry = pd.Timestamp(chain["expiry"].iloc[0])
        ctx = MarketContext(
            underlying, date, float(spot), feats, ivr, atm,
            chain[["opt_type", "strike", "close", "oi", "volume"]],
            dte=max((expiry - date).days, 1), expiry=expiry, lot_size=lot_size, step=50.0,
        )
        mc = None
        if model is not None:
            row = np.array([[feats.get(c, 0.0) for c in TA_FEATURES]])
            mc = float(model.predict_proba(row)[0])
        d = decide(ctx, dcfg, risk_state, meta_confidence=mc)
        if d.accepted:
            accepted["n"] += 1
            return d.structure
        rejects[d.reject_reason or "?"] = rejects.get(d.reject_reason or "?", 0) + 1
        return None

    result = backtest_strategy(eod, underlying, strategy, starting_capital=capital)
    rep = result.report()
    out["backtest"] = {
        "n_trades": rep["n_trades"], "net_pnl": rep["net_pnl"],
        "win_rate_pct": rep["win_rate_pct"], "max_drawdown_pct": rep["max_drawdown_pct"],
        "total_costs": rep["total_costs"], "signals_accepted": accepted["n"],
        "top_rejects": dict(sorted(rejects.items(), key=lambda kv: -kv[1])[:3]),
        "bias_audit": rep["bias_audit"],
    }
    return out


def _fmt(out: dict) -> str:
    L = ["═" * 66, f" END-TO-END DEMO — {out['underlying']} (SYNTHETIC DATA, numbers are illustrative)", "═" * 66]
    i = out["ingest"]
    L.append(f"[P1] Data      : {i['rows']:,} EOD rows over {i['days']} days · lot={i['lot_size']}")
    f = out["features"]
    L.append(f"[P2] Features  : {f['observations']} obs · {len(f['feature_columns'])} TA features")
    v = out["validation"]
    L.append(f"[P3] Validation: {v['labelled_events']} labelled events · "
             f"CPCV acc={v['cpcv_mean_accuracy']:.3f} · "
             f"{v['cpcv_pct_folds_above_half']:.0%} folds>0.5 · {v['cpcv_paths']} paths")
    b = out["backtest"]
    L.append(f"[P4/P5] Backtest: {b['n_trades']} trades · net ₹{b['net_pnl']:,.0f} · "
             f"win {b['win_rate_pct']:.0f}% · maxDD {b['max_drawdown_pct']:.1f}% · "
             f"costs ₹{b['total_costs']:,.0f}")
    L.append(f"          signals accepted={b['signals_accepted']} · top rejects={b['top_rejects']}")
    L.append(f"          bias-audit={b['bias_audit']}")
    L.append("═" * 66)
    return "\n".join(L)


def main():
    print(_fmt(run_demo()))


if __name__ == "__main__":
    main()
