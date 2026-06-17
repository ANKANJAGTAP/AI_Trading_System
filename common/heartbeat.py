"""Engine liveness heartbeat (P1#13).

A dedicated heartbeat task publishes a liveness doc INDEPENDENT of the trading
loops, so "is the engine actually alive?" is answered by the process itself — not
by whether the (gateable) slow loop happened to run. Pure classifier lives here;
the publishing loop is in engine/main.py and the API reads it to distinguish
degraded vs down.
"""
from __future__ import annotations

OK, DEGRADED, DOWN = "ok", "degraded", "down"


def heartbeat_status(doc: dict | None, age_s: float | None, max_age_s: float = 90.0,
                     live: bool = False) -> str:
    """Classify engine liveness from a heartbeat doc + its age.

    - no doc, or stale (age > max_age_s)         -> down
    - both DB and Redis unreachable               -> down
    - one of DB/Redis unreachable                 -> degraded
    - broker unreachable while in live mode        -> degraded
    - otherwise                                    -> ok
    """
    if not doc or age_s is None or age_s > max_age_s:
        return DOWN
    db_ok = bool(doc.get("db_ok"))
    redis_ok = bool(doc.get("redis_ok"))
    if not db_ok and not redis_ok:
        return DOWN
    if not db_ok or not redis_ok:
        return DEGRADED
    if live and doc.get("broker_ok") is False:
        return DEGRADED
    return OK
