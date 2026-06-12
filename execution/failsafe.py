"""Fail-safe handler (spec §8, mandatory).

On WebSocket disconnect, auth failure, repeated API errors, data staleness, or an
unhandled exception: square off ALL open positions, block new entries, alert the
operator, and halt until manual restart. Never hold exposure through an unknown
state. `engine_halted` in config_state is the block flag the Executor checks.
"""
from __future__ import annotations

from common.logging import get_logger
from common.state import set_state
from execution.models import ExitReason

log = get_logger("failsafe")


async def safe_exit_all(executor, reason: str) -> dict:
    closed: list[dict] = []
    errors: list[dict] = []
    for p in await executor.book.get_open(executor.mode):
        try:
            realized = await executor.close(p["id"], ExitReason.FAILSAFE)
            closed.append({"id": p["id"], "realized": realized})
        except Exception as exc:
            errors.append({"id": p["id"], "error": str(exc)})
            log.error("safe_exit_position_error", id=p["id"], error=str(exc))

    await set_state("engine_halted", True, "failsafe")
    await set_state("engine_paused", True, "failsafe")
    log.error("safe_exit_all", reason=reason, closed=len(closed), errors=len(errors))
    msg = (f"Reason: {reason}. Squared off {len(closed)} position(s), {len(errors)} error(s). "
           "New entries blocked until manual restart.")
    if executor.alerter:
        await executor.alerter.send_async("SAFE-EXIT TRIGGERED — engine halted", msg)
    try:
        from common.events import publish_event
        await publish_event("alert", {"kind": "safe_exit", "message": msg, "severity": "critical"})
    except Exception:
        pass
    return {"reason": reason, "closed": closed, "errors": errors}
