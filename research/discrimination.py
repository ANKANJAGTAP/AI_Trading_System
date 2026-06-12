"""Feature-discrimination report (Phase 4 diagnostic).

The blunt question before trusting any model: does ANY gate/feature actually separate
winners from losers? For each feature we median-split the labelled trades and compare
win-rate in the high half vs the low half. A large |lift| means the feature carries
signal; ~0 lift (like today's `confidence`: 0.921 vs 0.912) means it doesn't, and no
model built on it will help. Pure + unit-tested.
"""
from __future__ import annotations

from research.dataset import feature_names


def _value(sample: dict, feat: str) -> float:
    return float((sample.get("features") or {}).get(feat, 0.0))


def discriminate(samples: list[dict], min_per_bucket: int = 5) -> dict:
    """Per-feature win-rate(high half) vs win-rate(low half) + lift, sorted by |lift|."""
    n = len(samples)
    if n == 0:
        return {"n_samples": 0, "base_rate": 0.0, "features": []}
    base = sum(int(s.get("label", 0)) for s in samples) / n
    out, constant = [], []
    for feat in feature_names(samples):
        pairs = [(_value(s, feat), int(s.get("label", 0))) for s in samples]
        xs = sorted(v for v, _ in pairs)
        median = xs[len(xs) // 2]
        high = [lbl for v, lbl in pairs if v >= median]
        low = [lbl for v, lbl in pairs if v < median]
        if len(high) < min_per_bucket or len(low) < min_per_bucket:
            # Can't split -> the feature is (near-)constant => zero discriminating power.
            constant.append({"feature": feat, "note": "constant / no variance",
                             "win_rate_high": None, "win_rate_low": None, "lift": 0.0})
            continue
        wr_high = sum(high) / len(high)
        wr_low = sum(low) / len(low)
        out.append({
            "feature": feat, "threshold": round(median, 3),
            "n_high": len(high), "n_low": len(low),
            "win_rate_high": round(wr_high, 3), "win_rate_low": round(wr_low, 3),
            "lift": round(wr_high - wr_low, 3),
        })
    out.sort(key=lambda r: abs(r["lift"]), reverse=True)
    out += constant   # constant features listed last (informative: features don't vary)
    # A crude verdict so the operator doesn't over-read a tiny sample.
    best = abs(out[0]["lift"]) if out else 0.0
    verdict = ("insufficient_data" if n < 100 else
               "edge_present" if best >= 0.15 else
               "weak_or_none")
    return {"n_samples": n, "base_rate": round(base, 3), "verdict": verdict, "features": out}
