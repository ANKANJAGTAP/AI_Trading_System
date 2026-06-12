"""Gate-pipeline framework (spec §5/§6).

Every gate returns PASS/REJECT + a 0-1 score. A pipeline is a funnel: it stops at
the first hard REJECT and records the full per-gate trail. Gate scores feed the
confidence model (Phase 5); here confidence is a transparent mean of passed-gate
scores as a placeholder.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PASS = "PASS"
REJECT = "REJECT"


@dataclass
class GateResult:
    name: str
    passed: bool
    score: float                       # 0..1
    detail: dict = field(default_factory=dict)


@dataclass
class Signal:
    sleeve: str
    instrument: dict
    side: str                          # BUY / SELL
    setup: str
    entry: float
    stop: float
    target: float
    detail: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    decision: str                      # PASS / REJECT
    gates: list[GateResult]
    confidence: float
    signal: Signal | None = None
    reason: str | None = None

    @property
    def trail(self) -> list[dict]:
        return [{"name": g.name, "pass": g.passed, "score": round(g.score, 3)} for g in self.gates]


def _confidence(gates: list[GateResult]) -> float:
    scored = [g.score for g in gates if g.passed]
    return round(sum(scored) / len(scored), 4) if scored else 0.0


class GateRunner:
    """Funnel helper: add gates in order; short-circuit on first hard reject."""

    def __init__(self) -> None:
        self.gates: list[GateResult] = []

    def add(self, name: str, passed: bool, score: float, **detail) -> bool:
        self.gates.append(GateResult(name, passed, max(0.0, min(1.0, score)), detail))
        return passed

    def reject(self, reason: str) -> PipelineResult:
        return PipelineResult(REJECT, self.gates, _confidence(self.gates), None, reason)

    def accept(self, signal: Signal) -> PipelineResult:
        return PipelineResult(PASS, self.gates, _confidence(self.gates), signal)
