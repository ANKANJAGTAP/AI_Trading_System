"""Confidence model (spec §6).

A transparent weighted combination of the pipeline's gate scores into a single
0-1 confidence. Confidence maps to size WITHIN the R cap (the Risk Engine does
`effective_R = R * confidence`): strong agreement -> up to full 1R; weak -> a
fraction of R; below `min_confidence` -> skip. Weights live in config — no opaque
ML for v1.
"""
from __future__ import annotations


class ConfidenceModel:
    def __init__(self, config) -> None:
        c = config.system.confidence or {}
        self.weights = c.get("gate_weights", {})
        self.default_weight = float(c.get("default_weight", 1.0))
        self.min_confidence = float(c.get("min_confidence", 0.45))

    def score(self, gates) -> float:
        """Weighted average over ALL evaluated gates. Failed soft (non-rejecting)
        gates stay in the denominator with their low score and PENALIZE confidence —
        previously they vanished from the average, so a signal scraping past its soft
        filters scored the same as one passing them cleanly. Hard-gate failures never
        reach here (the pipeline rejects first)."""
        num = den = 0.0
        for g in gates:
            w = float(self.weights.get(g.name, self.default_weight))
            num += w * g.score
            den += w
        return round(num / den, 4) if den > 0 else 0.0

    def passes(self, confidence: float) -> bool:
        return confidence >= self.min_confidence
