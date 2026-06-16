"""Real pre-live checks (P0#2).

Replaces the old 4-boolean "checklist" (operator-set flags that proved nothing)
with a service that actually verifies the system is safe to go live, persists the
run with evidence, and is consumed by the mode-transition gate (P0#1).

This module is the generic FRAMEWORK (CheckResult + runner + persistence). The
concrete probes (broker, feed, reconcile, ...) are wired in `api.prelive_checks`,
where the read-only adapter / governor / redis live — keeping this layer free of
those dependencies and easy to unit-test with mocked checks.

Status vocabulary: 'pass' | 'warn' | 'fail'. Overall is 'pass' only if NO check
failed (warn does not block); any probe that raises is recorded as 'fail'
(fail-closed).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from common.logging import get_logger

log = get_logger("prelive")

PASS, WARN, FAIL = "pass", "warn", "fail"


def _now() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"


@dataclass
class CheckResult:
    name: str
    status: str = FAIL
    detail: str = ""
    evidence: dict = field(default_factory=dict)
    ts: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail,
                "evidence": self.evidence, "ts": self.ts or _now()}


def _coerce(name: str, raw) -> CheckResult:
    if isinstance(raw, CheckResult):
        raw.name = name
        return raw
    if isinstance(raw, bool):
        return CheckResult(name, PASS if raw else FAIL)
    if isinstance(raw, tuple):
        status = raw[0]
        detail = raw[1] if len(raw) > 1 else ""
        evidence = raw[2] if len(raw) > 2 else {}
        return CheckResult(name, status, detail, evidence)
    return CheckResult(name, FAIL, f"unrecognized check result: {type(raw).__name__}")


class PreLiveCheckService:
    """Runs a list of (name, async check) pairs and aggregates an overall verdict.

    A check returns a CheckResult, a bool, or a (status, detail[, evidence]) tuple.
    """

    def __init__(self, checks, persister=None):
        self.checks = checks
        self.persister = persister      # async (run: dict) -> None

    async def run_all(self, operator: str = "operator") -> dict:
        results: list[CheckResult] = []
        for name, fn in self.checks:
            try:
                cr = _coerce(name, await fn())
            except Exception as exc:                 # fail-closed on any probe error
                cr = CheckResult(name, FAIL, f"probe error: {type(exc).__name__}: {exc}")
            cr.ts = cr.ts or _now()
            results.append(cr)
        overall = PASS if all(c.status in (PASS, WARN) for c in results) else FAIL
        run = {"overall": overall, "operator": operator, "run_at": _now(),
               "checks": [c.as_dict() for c in results],
               "failed": [c.name for c in results if c.status == FAIL],
               "warned": [c.name for c in results if c.status == WARN]}
        if self.persister is not None:
            try:
                await self.persister(run)
            except Exception as exc:
                log.warning("prelive_persist_failed", error=str(exc))
        return run


async def persist_run(run: dict) -> None:
    """Write a run + its per-check results (with evidence) to the audit tables."""
    import json

    from common.db import execute, fetchval
    run_id = await fetchval(
        "INSERT INTO prelive_check_runs (operator, overall_status) VALUES ($1,$2) RETURNING id",
        run.get("operator", "operator"), run.get("overall", FAIL))
    for c in run.get("checks", []):
        await execute(
            "INSERT INTO prelive_check_results (run_id, name, status, detail, evidence) "
            "VALUES ($1,$2,$3,$4,$5::jsonb)",
            run_id, c["name"], c["status"], c.get("detail", ""),
            json.dumps(c.get("evidence", {})))
