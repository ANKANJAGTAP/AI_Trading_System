"""Atomic runtime execution mode (P0#1).

The single source of truth for "are we paper or live, and what does that imply".
Before this, mode lived in `config_state['execution_mode']` but the kill-switch,
capital reader, and risk engine each captured a mode at startup and never saw a
flip — so going live could run on paper capital and a paper-namespaced kill
switch. Now every consumer reads `RuntimeModeState` lazily from one row, so a
transition propagates everywhere on the next read.

The row is written ONLY by `common.mode_transition` (validated). We also mirror
the plain `execution_mode` key so any not-yet-migrated reader stays consistent.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, fields

from common.state import get_state, set_state

PAPER = "simulated_fill"
LIVE = "live"
_KEY = "runtime_mode"


@dataclass(frozen=True)
class RuntimeModeState:
    mode: str = PAPER                      # simulated_fill | live
    broker_account_id: str | None = None
    capital_source: str = "paper_static"  # paper_static | broker_live
    risk_profile: str = "paper"           # paper | live
    kill_switch_mode: str = "block_all"   # block_all | reducing_only
    position_namespace: str = PAPER       # value written to positions.mode / daily_pnl.mode
    updated_by: str = "system"
    updated_at: str = ""
    version: int = 0

    @property
    def is_live(self) -> bool:
        return self.mode == LIVE

    @property
    def use_broker_capital(self) -> bool:
        return self.capital_source == "broker_live"

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def _from_dict(d: dict) -> RuntimeModeState:
    names = {f.name for f in fields(RuntimeModeState)}
    return RuntimeModeState(**{k: v for k, v in d.items() if k in names})


def derive_for_mode(mode: str, broker_account_id: str | None = None,
                    updated_by: str = "system", version: int = 0) -> RuntimeModeState:
    """A consistent RuntimeModeState for a target mode. live => broker capital + live
    risk profile + live namespace; paper => static capital + paper profile/namespace.
    Anything not explicitly live is treated as paper (fail-closed)."""
    live = (mode == LIVE)
    return RuntimeModeState(
        mode=(LIVE if live else PAPER),
        broker_account_id=broker_account_id,
        capital_source=("broker_live" if live else "paper_static"),
        risk_profile=("live" if live else "paper"),
        kill_switch_mode="block_all",
        position_namespace=(LIVE if live else PAPER),
        updated_by=updated_by,
        updated_at=dt.datetime.utcnow().isoformat() + "Z",
        version=version,
    )


async def load_runtime_mode() -> RuntimeModeState:
    """Read the current state. Falls back to the legacy `execution_mode` key (so
    deployments work before the 0014 migration), defaulting to safe paper."""
    raw = await get_state(_KEY, None)
    if isinstance(raw, dict) and raw.get("mode"):
        try:
            return _from_dict(raw)
        except Exception:
            pass
    legacy = await get_state("execution_mode", PAPER)
    return derive_for_mode(legacy if legacy in (PAPER, LIVE) else PAPER)


# Always-fresh on purpose: one indexed read, same cost as the get_state calls
# already sprinkled through the hot paths. No stale-cache risk on a mode flip.
async def get_runtime_mode() -> RuntimeModeState:
    return await load_runtime_mode()


async def active_mode() -> str:
    return (await load_runtime_mode()).mode


async def write_runtime_mode(state: RuntimeModeState, updated_by: str = "operator") -> RuntimeModeState:
    """Persist a new state (version-bumped) and mirror the legacy execution_mode key.
    Only `common.mode_transition` should call this."""
    current = await load_runtime_mode()
    new = derive_for_mode(state.mode, state.broker_account_id, updated_by, current.version + 1)
    await set_state(_KEY, new.to_dict(), updated_by)
    await set_state("execution_mode", new.mode, updated_by)   # legacy mirror
    return new
