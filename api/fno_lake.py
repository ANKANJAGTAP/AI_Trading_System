"""
F&O research API over the curated dataplatform lake (Pillars 1-5).

Read-only endpoints the dashboard can call to see — on the SAME point-in-time
data the models train/backtest on — the things the live tick view can't show:

  * /api/fno/lake     : coverage (rows / trading days / span) per underlying,
  * /api/fno/analytics: per-day option analytics (PCR / ATM-IV / net-GEX /
                        max-pain / skew) off the captured chains,
  * /api/fno/features : the TA + options feature matrix (point-in-time).

Every pillar call here is synchronous and CPU-bound, so it runs in a worker
thread (asyncio.to_thread) to keep the API event loop responsive. Nothing here
touches the trading path, the broker, or the live order book — it only reads the
Parquet lake, so it is always safe to call.
"""
from __future__ import annotations

import asyncio
import datetime as dt

from common.logging import get_logger

log = get_logger("api_fno_lake")

TA_FEATURES = ["ema_20", "rsi_14", "atr_pct_14", "macd_hist", "rvol_20", "bb_pctb_20"]
DEFAULT_UNDERLYINGS = ("NIFTY", "FINNIFTY", "SENSEX")


def _d(s):
    return dt.date.fromisoformat(s) if isinstance(s, str) else s


def _records(df, tail: int | None = None) -> list[dict]:
    """DataFrame -> JSON-ready records with a stringified date index."""
    if df is None or len(df) == 0:
        return []
    d = (df.tail(tail) if tail else df).reset_index()
    idxcol = d.columns[0]
    d[idxcol] = d[idxcol].astype(str)
    if idxcol in ("index", "level_0"):
        d = d.rename(columns={idxcol: "trade_date"})
    return d.round(4).to_dict("records")


def _rolling_iv_rank(atm_iv, window: int = 40):
    import numpy as np
    def rank(x):
        lo, hi = np.nanmin(x), np.nanmax(x)
        return (x[-1] - lo) / (hi - lo) * 100 if hi > lo else 50.0
    return atm_iv.rolling(window, min_periods=10).apply(rank, raw=True)


# --------------------------------------------------------------------------- #
# synchronous cores (run in a worker thread)
# --------------------------------------------------------------------------- #
def _summary_sync(underlyings, start, end) -> dict:
    from dataplatform.storage import ParquetLake
    lake = ParquetLake()
    rows = []
    for u in underlyings:
        df = lake.read_eod(underlying=u, start=_d(start), end=_d(end))
        if len(df):
            rows.append({"underlying": u, "rows": int(len(df)),
                         "days": int(df["trade_date"].nunique()),
                         "fut": int((df["instrument"] == "FUT").sum()),
                         "opt": int((df["instrument"] == "OPT").sum()),
                         "first": str(df["trade_date"].min()),
                         "last": str(df["trade_date"].max())})
        else:
            rows.append({"underlying": u, "rows": 0, "days": 0, "fut": 0, "opt": 0})
    return {"start": str(start), "end": str(end), "underlyings": rows}


def _analytics_sync(underlying, start, end, tail) -> dict:
    from dataplatform.storage import ParquetLake
    from features.engine import option_features_timeseries, underlying_daily_from_eod
    eod = ParquetLake().read_eod(underlying=underlying, start=_d(start), end=_d(end))
    if len(eod) == 0:
        return {"underlying": underlying, "rows": 0, "analytics": []}
    daily = underlying_daily_from_eod(eod, underlying)
    of = option_features_timeseries(eod, underlying)
    cols = [c for c in ["pcr_oi", "atm_iv", "net_gex", "max_pain", "skew"] if c in of.columns]
    last_close = float(daily["close"].iloc[-1]) if len(daily) else None
    return {"underlying": underlying, "rows": int(len(eod)),
            "days": int(eod["trade_date"].nunique()),
            "underlying_last_close": last_close,
            "analytics": _records(of[cols] if cols else of, tail)}


def _features_sync(underlying, start, end, tail) -> dict:
    from dataplatform.storage import ParquetLake
    from features.engine import FeatureEngine, underlying_daily_from_eod
    eod = ParquetLake().read_eod(underlying=underlying, start=_d(start), end=_d(end))
    if len(eod) == 0:
        return {"underlying": underlying, "rows": 0, "features": []}
    daily = underlying_daily_from_eod(eod, underlying)
    ta = FeatureEngine(TA_FEATURES).compute(daily) if len(daily) else None
    usable = int(ta.dropna(how="any").shape[0]) if ta is not None and len(ta) else 0
    return {"underlying": underlying, "feature_ids": TA_FEATURES,
            "daily_rows": int(len(daily)), "usable_rows": usable,
            "note": None if usable else "need ~20+ trading days for the 20-period features",
            "features": _records(ta, tail)}


def _backtest_sync(underlying, start, end, capital, per_trade_pct) -> dict:
    """Run the fno_signals decision engine over the fno_backtest engine on the
    lake — the same chain (P1->P2->P5 over P4) the end-to-end demo runs, but on
    real captured data. Defined-risk structures only; bias-audited report."""
    import pandas as pd
    from dataplatform.storage import ParquetLake
    from dataplatform.contracts import ContractSpecResolver
    from features.engine import build_feature_matrix, option_features_timeseries
    from fno_backtest.engine import backtest_strategy
    from fno_signals import MarketContext, DecisionConfig, SizingConfig, RiskState, decide

    eod = ParquetLake().read_eod(underlying=underlying, start=_d(start), end=_d(end))
    if len(eod) == 0:
        return {"underlying": underlying, "error": "no lake data in range", "n_trades": 0}
    lot_size = int(ContractSpecResolver().lot_size(underlying, _d(end)))
    fmat = build_feature_matrix(eod, underlying, feature_ids=TA_FEATURES)
    opt_feats = option_features_timeseries(eod, underlying)
    iv_rank = _rolling_iv_rank(opt_feats["atm_iv"]) if not opt_feats.empty else pd.Series(dtype=float)
    dcfg = DecisionConfig(sizing=SizingConfig(capital=capital, per_trade_risk_pct=per_trade_pct))
    risk_state = RiskState(capital=capital)
    stats = {"accepted": 0, "rejects": {}}

    def strategy(date, chain, spot):
        if date not in fmat.index:
            return None
        feats = fmat.loc[date].to_dict()
        if any(pd.isna(feats.get(c)) for c in TA_FEATURES):
            return None                                  # warmup not satisfied -> no trade
        ivr = iv_rank.get(date, 50.0)
        ivr = 50.0 if pd.isna(ivr) else float(ivr)
        atm = opt_feats["atm_iv"].get(date, 0.18) if not opt_feats.empty else 0.18
        atm = 0.18 if (pd.isna(atm) or atm <= 0) else float(atm)
        expiry = pd.Timestamp(chain["expiry"].iloc[0])
        ctx = MarketContext(
            underlying, date, float(spot), feats, ivr, atm,
            chain[["opt_type", "strike", "close", "oi", "volume"]],
            dte=max((expiry - date).days, 1), expiry=expiry, lot_size=lot_size, step=50.0)
        d = decide(ctx, dcfg, risk_state, meta_confidence=None)
        if d.accepted:
            stats["accepted"] += 1
            return d.structure
        r = d.reject_reason or "?"
        stats["rejects"][r] = stats["rejects"].get(r, 0) + 1
        return None

    result = backtest_strategy(eod, underlying, strategy, starting_capital=capital)
    rep = result.report()
    return {"underlying": underlying, "rows": int(len(eod)),
            "days": int(eod["trade_date"].nunique()), "lot_size": lot_size,
            "capital": capital, "per_trade_pct": per_trade_pct,
            "n_trades": rep.get("n_trades"), "net_pnl": rep.get("net_pnl"),
            "win_rate_pct": rep.get("win_rate_pct"), "max_drawdown_pct": rep.get("max_drawdown_pct"),
            "total_costs": rep.get("total_costs"), "signals_accepted": stats["accepted"],
            "top_rejects": dict(sorted(stats["rejects"].items(), key=lambda kv: -kv[1])[:5]),
            "bias_audit": rep.get("bias_audit")}


# --------------------------------------------------------------------------- #
# async API surface
# --------------------------------------------------------------------------- #
async def lake_summary(underlyings=DEFAULT_UNDERLYINGS, start: str = "2026-01-01",
                       end: str | None = None) -> dict:
    end = end or str(dt.date.today())
    return await asyncio.to_thread(_summary_sync, tuple(underlyings), start, end)


async def analytics(underlying: str = "NIFTY", start: str = "2026-01-01",
                    end: str | None = None, tail: int = 30) -> dict:
    end = end or str(dt.date.today())
    return await asyncio.to_thread(_analytics_sync, underlying, start, end, tail)


async def features(underlying: str = "NIFTY", start: str = "2026-01-01",
                   end: str | None = None, tail: int = 30) -> dict:
    end = end or str(dt.date.today())
    return await asyncio.to_thread(_features_sync, underlying, start, end, tail)


async def backtest(underlying: str = "NIFTY", start: str = "2026-01-01",
                   end: str | None = None, capital: float = 1_000_000.0,
                   per_trade_pct: float = 1.0) -> dict:
    end = end or str(dt.date.today())
    return await asyncio.to_thread(_backtest_sync, underlying, start, end, capital, per_trade_pct)
