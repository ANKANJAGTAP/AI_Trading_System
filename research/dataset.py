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
