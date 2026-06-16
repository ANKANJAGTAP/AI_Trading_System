"""Validated paper<->live mode transitions (P0#1).

The ONLY sanctioned way to change execution mode. Going live is fail-closed: it
requires an explicit confirm token, an inactive kill-switch, all pre-live checks
passing, and (optionally) a clean broker reconciliation. Going back to paper
requires open live positions to be flattened first (or an explicit override).

Validators are injected as callables so this module stays decoupled from the API,
engine, and broker. With `RuntimeModeState` read lazily everywhere, a successful
transition just writes the new state — consumers pick it up on their next read.
"""
from __future__ import annotations

from common.errors import ModeTransitionRejected
from common.runtime_mode import (LIVE, PAPER, RuntimeModeState, derive_for_mode,
                                  get_runtime_mode, write_runtime_mode)


def _failed_checks(results) -> list[str]:
    """Names of failing pre-live checks. Accepts a {name: bool} map (the legacy
    checklist) or a {'checks': [{name,status}]} structure (the P0#2 service)."""
    if results is None:
        return ["pre-live checks returned nothing"]
    if isinstance(results, dict):
        if "checks" in results:
            return [c.get("name", "?") for c in (results.get("checks") or [])
                    if c.get("status") not in ("pass", "warn")]
        return [k for k, v in results.items() if not v]
    # object exposing .failed() or .ok
    failed = getattr(results, "failed", None)
    if callable(failed):
        return list(failed())
    return [] if getattr(results, "ok", False) else ["pre-live checks not ok"]


async def request_transition(
    target_mode: str,
    operator: str,
    *,
    confirm_token: str | None = None,
    prelive_runner=None,           # async () -> checklist result (required for live)
    kill_switch_active=None,       # async () -> bool
    reconcile_check=None,          # async () -> (ok: bool, detail)
    open_live_positions=None,      # async () -> int   (for live -> paper)
    allow_unflattened_downgrade: bool = False,
    broker_account_id: str | None = None,
) -> RuntimeModeState:
    """Validate and apply a mode transition. Raises ModeTransitionRejected on any
    failure (nothing is written). Idempotent when already in the target mode."""
    if target_mode not in (PAPER, LIVE):
        raise ModeTransitionRejected(f"unknown mode '{target_mode}'")

    current = await get_runtime_mode()
    if current.mode == target_mode:
        return current  # no-op

    reasons: list[str] = []

    if target_mode == LIVE:
        if confirm_token != "LIVE":
            reasons.append("going live requires confirm_token='LIVE'")
        if kill_switch_active is not None and await kill_switch_active():
            reasons.append("kill-switch is active — reset it before going live")
        if prelive_runner is None:
            reasons.append("pre-live checks not configured (fail-closed)")
        else:
            failed = _failed_checks(await prelive_runner())
            if failed:
                reasons.append("pre-live checks failed: " + ", ".join(failed))
        if reconcile_check is not None:
            ok, detail = await reconcile_check()
            if not ok:
                reasons.append(f"broker reconciliation not clean: {detail}")
    else:  # LIVE -> PAPER
        if open_live_positions is not None and not allow_unflattened_downgrade:
            n = await open_live_positions()
            if n > 0:
                reasons.append(f"{n} open live position(s) — flatten/reconcile first "
                               "or pass allow_unflattened_downgrade")

    if reasons:
        raise ModeTransitionRejected(reasons)

    return await write_runtime_mode(
        derive_for_mode(target_mode, broker_account_id, operator), operator)
