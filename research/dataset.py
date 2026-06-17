"""Build the meta-labeling dataset from the audit trail.

A sample = {"features": {name: value}, "label": won?}. Features are the rich per-signal
vector captured at decision time (continuous context + gate scores); label = did the
resulting trade win (realized P&L > 0). Only PASS signals that became closed positions
are labelled. The pure helpers (feature_names / to_matrix) are unit-tested.
"""
from __future__ import annotations

import json

from common.db import fetch


def feature_names(samples: list[dict]) -> list[str]:
    """Stable sorted union of every feature seen across samples."""
    names: set[str] = set()
    for s in samples:
        names.update((s.get("features") or {}).keys())
    return sorted(names)


def to_matrix(samples: list[dict], features: list[str]) -> tuple[list[list[float]], list[int]]:
    X, y = [], []
    for s in samples:
        f = s.get("features") or {}
        X.append([float(f.get(k, 0.0)) for k in features])
        y.append(int(s.get("label", 0)))
    return X, y


async def build_dataset() -> list[dict]:
    """One sample per PASS signal whose trade is FULLY closed (every leg of the
    correlation — a half-closed structure would mislabel). Features = the stored rich
    vector (signals.features) merged with the gate scores; label = combined realized
    P&L > 0. Ordered by signal id (time) so callers can split temporally — a random
    split would leak the future into training."""
    rows = await fetch(
        "SELECT s.id, s.confidence, s.features, "
        "COALESCE(SUM(p.realized_pnl) FILTER (WHERE p.status='closed'), 0) AS pnl "
        "FROM signals s JOIN positions p ON p.correlation_id = s.correlation_id "
        "WHERE s.decision='PASS' "
        "GROUP BY s.id, s.confidence, s.features "
        "HAVING COUNT(*) FILTER (WHERE p.status <> 'closed') = 0 "
        "ORDER BY s.id")
    samples: list[dict] = []
    for r in rows:
        feats = r["features"]
        if isinstance(feats, str):
            feats = json.loads(feats) if feats else {}
        feats = dict(feats or {})
        for g in await fetch("SELECT gate_name, score FROM gate_results WHERE signal_id=$1", r["id"]):
            feats[f"gate_{g['gate_name']}"] = float(g["score"] or 0.0)
        feats.setdefault("confidence", float(r["confidence"] or 0.0))
        samples.append({"id": int(r["id"]), "features": feats,
                        "label": 1 if float(r["pnl"]) > 0 else 0})
    return samples


async def build_triple_barrier_dataset(pt_pct: float = 0.02, sl_pct: float = 0.01,
                                       max_holding: int = 24, interval: str = "5m") -> list[dict]:
    """Alternative labels (#27): instead of "did the realized trade win", label each
    PASS signal by its TRIPLE-BARRIER outcome over the FORWARD price path — did price
    reach +pt_pct (target) before -sl_pct (stop) within max_holding bars. Path- and
    horizon-aware and independent of the executor's actual exit. Ordered by signal id
    (time) so callers can split temporally without leakage."""
    from datetime import timedelta
    from data.store import load_candles_range_df
    from research.triple_barrier import barrier_to_meta_label, triple_barrier_label

    rows = await fetch(
        "SELECT id, confidence, features, instrument_token, ts, side, entry_price "
        "FROM signals WHERE decision='PASS' AND instrument_token IS NOT NULL "
        "AND entry_price IS NOT NULL ORDER BY id")
    samples: list[dict] = []
    for r in rows:
        feats = r["features"]
        if isinstance(feats, str):
            feats = json.loads(feats) if feats else {}
        feats = dict(feats or {})
        for g in await fetch("SELECT gate_name, score FROM gate_results WHERE signal_id=$1", r["id"]):
            feats[f"gate_{g['gate_name']}"] = float(g["score"] or 0.0)
        feats.setdefault("confidence", float(r["confidence"] or 0.0))
        try:
            df = await load_candles_range_df(int(r["instrument_token"]), interval,
                                             r["ts"], r["ts"] + timedelta(days=10))
        except Exception:
            df = None
        if df is None or df.empty or len(df) < 2:
            continue
        highs = [float(x) for x in df["high"].tolist()][1:]   # strictly AFTER the entry bar
        lows = [float(x) for x in df["low"].tolist()][1:]
        res = triple_barrier_label(highs, lows, float(r["entry_price"]),
                                   (r["side"] or "BUY"), pt_pct=pt_pct, sl_pct=sl_pct,
                                   max_holding=max_holding)
        samples.append({"id": int(r["id"]), "features": feats,
                        "label": barrier_to_meta_label(res["label"])})
    return samples
