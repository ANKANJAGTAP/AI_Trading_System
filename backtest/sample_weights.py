"""Sample weights for overlapping financial labels (§10 Phase 2) — pure, no I/O.

Two López de Prado corrections to naive equal-weighting:
  * Label UNIQUENESS — when label windows overlap in time they share information, so
    each should count less. Weight = mean(1/concurrency) over the label's lifespan.
  * TIME DECAY — markets drift, so older samples count less, linearly down to `last`.

These plug into the meta-labeler's `sample_weight` so it isn't fooled by redundant,
overlapping, or stale observations.
"""
from __future__ import annotations


def time_decay_weights(n: int, last: float = 0.5) -> list[float]:
    """Linear time decay: oldest sample weight = `last`, newest = 1.0 (index 0 = oldest).
    `last` may be negative to fully drop the oldest tail (clamped at 0)."""
    if n <= 0:
        return []
    if n == 1:
        return [1.0]
    return [round(max(0.0, last + (1.0 - last) * i / (n - 1)), 6) for i in range(n)]


def uniqueness_weights(spans: list[tuple]) -> list[float]:
    """`spans`: list of inclusive (start, end) index ranges per label. Returns each
    label's average uniqueness = mean(1/concurrency) over its span. Isolated labels ->
    1.0; fully overlapping pair -> 0.5."""
    if not spans:
        return []
    max_t = max(e for _, e in spans)
    conc = [0] * (max_t + 1)
    for s, e in spans:
        for t in range(s, e + 1):
            conc[t] += 1
    out = []
    for s, e in spans:
        out.append(round(sum(1.0 / conc[t] for t in range(s, e + 1)) / (e - s + 1), 6))
    return out
