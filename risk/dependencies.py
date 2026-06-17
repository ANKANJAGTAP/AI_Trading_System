"""Per-mode risk-dependency policy (P1#9).

In LIVE, a missing critical dependency (broker margin, market data, instrument
metadata, calendar, risk config, kill-switch) fails CLOSED — the sizing call is
rejected rather than proceeding without that safeguard. In PAPER the same gap
degrades with a warning (the prior fail-open behavior), so paper is unchanged.

Pure: feed it (risk_profile, available) and it returns the disposition.
"""
from __future__ import annotations

OK, DEGRADED, FAILED = "ok", "degraded", "failed"

# The critical live dependencies (informational; the policy decision is per-call).
CRITICAL = ("broker_margin", "market_data", "instrument_meta", "calendar",
            "risk_config", "kill_switch")


def dep_disposition(risk_profile: str, available: bool) -> str:
    """OK when available; otherwise FAILED in live (fail-closed), DEGRADED in paper."""
    if available:
        return OK
    return FAILED if risk_profile == "live" else DEGRADED


def must_block(risk_profile: str, available: bool) -> bool:
    """True when a missing dependency must BLOCK the call (live + unavailable)."""
    return dep_disposition(risk_profile, available) == FAILED
