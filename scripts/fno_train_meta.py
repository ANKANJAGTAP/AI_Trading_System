"""Train an F&O meta-label model from the VALIDATED backtest (offline).

The live meta-label trainer (`train_meta.py`) learns from the engine's recorded
signal audit trail — which only fills as the paper engine trades. To train on the
3-year edge we just validated *now*, this runs the same fno_signals decision engine
over the bhavcopy chains, captures each signal's feature vector at decision time,
labels it by the structure's realised win/loss, and runs it through the SAME purged
expanding-window CV + validation gate as `api.research.train_and_register` (reusing
`research.meta_label` + `research.dataset`). It saves the model JSON; it does NOT
auto-activate it live (a backtest-trained filter is for inspection until paper
confirms it).

    sudo docker compose exec -T api python scripts/fno_train_meta.py \
        --underlying NIFTY --from 2023-06-20 --to 2026-06-20 --capital 5000000

The model's job is a FILTER: of the signals it would let through, what fraction win
(precision) vs the base rate (lift). A positive average lift across most folds =
the features carry real, generalising information beyond the raw strategy.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---- pure helpers (stdlib only -> unit-testable) -----------------------------
def cv_index_splits(n: int, folds: int, embargo: int):
    """Purged expanding-window CV index splits (mirrors train_and_register). Pure.

    Returns [(train_slice, test_slice), ...]; train ends `embargo` samples before the
    test block so the boundary can't leak. [] if there isn't enough data per fold."""
    seg = n // (folds + 1)
    if seg < 1:
        return []
    out = []
    for k in range(1, folds + 1):
        tr_end = max(1, k * seg - embargo)
        te_start = k * seg
        te_end = (k + 1) * seg if k < folds else n
        out.append((slice(0, tr_end), slice(te_start, te_end)))
    return out


def build_samples_from_trades(captured: dict, records: list) -> list[dict]:
    """Join per-signal features (captured by entry day) to realised trade P&L. Pure.

    captured: {date_key: feature_dict}; records: [{entry_date, net, ...}].
    -> [{features, label}] in record (temporal) order; label = realised net > 0."""
    cap_by_day = {str(k)[:10]: v for k, v in captured.items()}
    out = []
    for r in records:
        fv = cap_by_day.get(str(r.get("entry_date"))[:10])
        if fv is None:
            continue
        out.append({"features": fv, "label": int(float(r.get("net", 0.0) or 0.0) > 0)})
    return out


def _num(v):
    try:
        f = float(v)
        return f if f == f else 0.0          # NaN -> 0.0
    except (TypeError, ValueError):
        return 0.0


def roc_auc(y_true: list, scores: list) -> float:
    """ROC-AUC via the rank / Mann-Whitney-U identity (no sklearn). Pure.
    0.5 = no discrimination; returns 0.5 if one class is absent."""
    if not y_true:
        return 0.5
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):                    # average ranks within tied scores
        j = i
        while j < len(order) and scores[order[j]] == scores[order[i]]:
            j += 1
        avg = (i + j - 1) / 2.0 + 1.0
        for k in range(i, j):
            ranks[order[k]] = avg
        i = j
    pos = sum(1 for y in y_true if y == 1)
    neg = len(y_true) - pos
    if pos == 0 or neg == 0:
        return 0.5
    sum_pos = sum(r for r, y in zip(ranks, y_true) if y == 1)
    return (sum_pos - pos * (pos + 1) / 2.0) / (pos * neg)


# ---- offline runner (heavy imports deferred) --------------------------------
def _run(args) -> int:
    import pandas as pd
    from dataplatform.storage import ParquetLake
    from dataplatform.contracts import ContractSpecResolver
    from features.engine import build_feature_matrix, option_features_timeseries
    from fno_backtest.engine import backtest_strategy
    from fno_signals import DecisionConfig, MarketContext, RiskState, SizingConfig, decide
    from api.fno_lake import TA_FEATURES, _rolling_iv_rank
    from research.dataset import feature_names, to_matrix
    from research.meta_label import evaluate, feature_importance, predict_proba, train

    try:
        start, end = dt.date.fromisoformat(args.from_date), dt.date.fromisoformat(args.to_date)
    except ValueError:
        print("ERROR: --from/--to must be YYYY-MM-DD")
        return 2

    eod = ParquetLake().read_eod(underlying=args.underlying, start=start, end=end)
    if len(eod) == 0:
        print(f"ERROR: no lake data for {args.underlying} in {start}..{end}")
        return 1

    lot_size = int(ContractSpecResolver().lot_size(args.underlying, end))
    fmat = build_feature_matrix(eod, args.underlying, feature_ids=TA_FEATURES)
    opt_feats = option_features_timeseries(eod, args.underlying)
    iv_rank = _rolling_iv_rank(opt_feats["atm_iv"]) if not opt_feats.empty else pd.Series(dtype=float)
    has_pcr = (not opt_feats.empty) and ("pcr_oi" in opt_feats.columns)
    base = DecisionConfig(sizing=SizingConfig(capital=args.capital, per_trade_risk_pct=args.per_trade_pct))
    risk_state = RiskState(capital=args.capital)

    captured: dict = {}

    def strategy(date, chain, spot):
        if date not in fmat.index:
            return None
        feats = fmat.loc[date].to_dict()
        if any(pd.isna(feats.get(c)) for c in TA_FEATURES):
            return None
        ivr = iv_rank.get(date, 50.0)
        ivr = 50.0 if pd.isna(ivr) else float(ivr)
        atm = opt_feats["atm_iv"].get(date, 0.18) if not opt_feats.empty else 0.18
        atm = 0.18 if (pd.isna(atm) or atm <= 0) else float(atm)
        expiry = pd.Timestamp(chain["expiry"].iloc[0])
        dte = max((expiry - date).days, 1)
        ctx = MarketContext(args.underlying, date, float(spot), feats, ivr, atm,
                            chain[["opt_type", "strike", "close", "oi", "volume"]],
                            dte=dte, expiry=expiry, lot_size=lot_size, step=50.0)
        d = decide(ctx, base, risk_state, meta_confidence=None)
        if not d.accepted:
            return None
        fv = {f: _num(feats.get(f)) for f in TA_FEATURES}
        fv["iv_rank"] = float(ivr)
        fv["atm_iv"] = float(atm)
        fv["dte"] = float(dte)
        fv["moneyness_pct"] = round((float(spot) - _num(chain["strike"].median())) / float(spot) * 100, 4)
        # enriched chain context (the honest AUC lever): dealer-positioning (net GEX),
        # vol skew, PCR, and max-pain pull — captured point-in-time at the signal.
        def _of(col):
            return _num(opt_feats[col].get(date)) if (not opt_feats.empty and col in opt_feats.columns) else 0.0
        fv["pcr"] = _of("pcr_oi")
        fv["net_gex"] = _of("net_gex")
        fv["skew"] = _of("skew")
        mp = _of("max_pain")
        fv["max_pain_dist_pct"] = round((mp - float(spot)) / float(spot) * 100, 4) if mp else 0.0
        captured[date] = fv
        return d.structure

    res = backtest_strategy(eod, args.underlying, strategy, starting_capital=args.capital)
    records = res.trades.to_dict("records") if len(res.trades) else []
    samples = build_samples_from_trades(captured, records)

    n = len(samples)
    wins = sum(s["label"] for s in samples)
    print(f"dataset: {n} signals · {wins} wins / {n - wins} losses · base_rate {wins / max(n, 1) * 100:.0f}%")
    if n < args.min_samples:
        print(f"too few samples ({n} < {args.min_samples})")
        return 1
    if wins < args.min_class or (n - wins) < args.min_class:
        print(f"class imbalance ({wins}/{n - wins}; need >= {args.min_class} each)")
        return 1

    feats = feature_names(samples)
    fold_metrics = []
    oos_scores: list[float] = []
    oos_labels: list[int] = []
    for tr_sl, te_sl in cv_index_splits(n, args.folds, embargo=1):
        tr, te = samples[tr_sl], samples[te_sl]
        tw = sum(s["label"] for s in tr)
        if len(te) < args.min_test_fold or tw == 0 or tw == len(tr):
            continue
        p = train(*to_matrix(tr, feats), class_weight=True)
        fold_metrics.append(evaluate(p, *to_matrix(te, feats)))
        xte, yte = to_matrix(te, feats)
        oos_scores += [predict_proba(p, row) for row in xte]
        oos_labels += list(yte)
    split_desc = f"purged_expanding_{args.folds}fold_embargo1"
    if not fold_metrics:                                  # fall back to one temporal split
        cut = max(1, int(n * 0.8))
        tr, te = samples[:cut], samples[cut:]
        if len(te) >= args.min_test_fold:
            p = train(*to_matrix(tr, feats), class_weight=True)
            fold_metrics.append(evaluate(p, *to_matrix(te, feats)))
            xte, yte = to_matrix(te, feats)
            oos_scores += [predict_proba(p, row) for row in xte]
            oos_labels += list(yte)
            split_desc = "temporal_80_20"
    auc = roc_auc(oos_labels, oos_scores)
    if not fold_metrics:
        print("no evaluable CV folds (degenerate class distribution)")
        return 1

    mean_acc = st.mean(m["accuracy"] for m in fold_metrics)
    mean_lift = st.mean(m["lift"] for m in fold_metrics)
    mean_base = st.mean(m["base_rate"] for m in fold_metrics)
    mean_prec = st.mean(m["precision_1"] for m in fold_metrics)
    pos_folds = sum(1 for m in fold_metrics if m["lift"] > 0)
    majority = max(mean_base, 1.0 - mean_base)
    validated = (mean_acc >= majority + args.min_lift / 2
                 and mean_lift >= args.min_lift
                 and pos_folds >= math.ceil(0.75 * len(fold_metrics)))

    final = train(*to_matrix(samples, feats), class_weight=True)
    final["deploy"] = {"veto_below": 0.40, "neutral_above": 0.55, "soft_floor": 0.6}
    importance = feature_importance(final, feats)[:10]

    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"fno_meta_{args.underlying}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"underlying": args.underlying, "features": feats, "params": final,
                   "metrics": {"accuracy": round(mean_acc, 3), "base_rate": round(mean_base, 3),
                               "lift": round(mean_lift, 3), "precision_1": round(mean_prec, 3),
                               "folds": len(fold_metrics), "positive_folds": pos_folds,
                               "auc": round(auc, 3), "n_samples": n,
                               "validated": validated, "split": split_desc}},
                  fh, indent=2, default=str)

    print(f"\nCV ({split_desc}):  AUC {auc:.3f}  acc {mean_acc * 100:.0f}%  "
          f"precision(let-through) {mean_prec * 100:.0f}%  lift {mean_lift * 100:+.0f}pp  "
          f"(base {mean_base * 100:.0f}%)")
    print(f"folds positive: {pos_folds}/{len(fold_metrics)}   VALIDATED={validated}")
    if not validated:
        print("NOT validated — features don't beat the base rate out-of-sample reliably "
              "(the raw strategy may already capture the edge; a filter adds nothing here).")
    print("top features:")
    for f in importance[:8]:
        print(f"    {f['feature']:<16} {f['weight']:+.2f}")
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
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--min-lift", dest="min_lift", type=float, default=0.02, help="avg OOS lift bar (0.02=2pp)")
    p.add_argument("--min-samples", dest="min_samples", type=int, default=80)
    p.add_argument("--min-class", dest="min_class", type=int, default=10)
    p.add_argument("--min-test-fold", dest="min_test_fold", type=int, default=20)
    p.add_argument("--out-dir", default="backtest_sweeps")
    raise SystemExit(_run(p.parse_args()))


if __name__ == "__main__":
    main()
