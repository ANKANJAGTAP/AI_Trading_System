"""Daily max-loss kill switch (spec §4).

If realized + unrealized day PnL <= -daily_max_loss_pct of starting capital:
block new entries, flag for flatten (Phase 3 executes), alert, and stay halted
until a manual reset next session. State persists in `config_state` +`daily_pnl`.
"""
from __future__ import annotations

from common.db import execute, fetchrow
from common.logging import get_logger
from common.market_time import today_ist
from common.state import get_state, set_state
from risk.models import KillSwitchStatus

log = get_logger("kill_switch")
_ACTIVE_KEY = "kill_switch_active"


class KillSwitch:
    def __init__(self, config, mode: str = "simulated_fill", alerter=None,
                 daily_loss_pct: float | None = None) -> None:
        self.config = config
        self.mode = mode                       # fallback namespace only
        self.alerter = alerter
        self.daily_loss_pct = daily_loss_pct   # paper overlay; None -> spec default
        self.flatten_on_trip = bool((config.risk.kill_switch or {}).get("flatten_on_trip", True))

    async def _ns(self) -> str:
        """Active position namespace (P0#1): daily_pnl rows are keyed by the live
        runtime mode, so a flip moves the kill-switch to the live namespace too.
        Falls back to the constructor mode if the runtime state can't be read."""
        try:
            from common.runtime_mode import load_runtime_mode
            return (await load_runtime_mode()).position_namespace
        except Exception:
            return self.mode

    async def ensure_daily_row(self, starting_capital: float) -> None:
        pct = self.daily_loss_pct or self.config.risk.daily_max_loss_pct.default
        limit = pct / 100.0 * starting_capital
        await execute(
            "INSERT INTO daily_pnl (trade_date, mode, starting_capital, max_loss_limit) "
            "VALUES ($1,$2,$3,$4) ON CONFLICT (trade_date, mode) DO UPDATE SET "
            "starting_capital = EXCLUDED.starting_capital, max_loss_limit = EXCLUDED.max_loss_limit",
            today_ist(), await self._ns(), starting_capital, -abs(limit),
        )

    async def is_active(self) -> bool:
        return bool(await get_state(_ACTIVE_KEY, False))

    async def status(self) -> KillSwitchStatus:
        active = await self.is_active()
        row = await fetchrow(
            "SELECT * FROM daily_pnl WHERE trade_date = $1 AND mode = $2", today_ist(), await self._ns()
        )
        if not row:
            return KillSwitchStatus(active, False, 0.0, 0.0, 0.0, 0.0, 0.0)
        realized = float(row["realized_pnl"] or 0)
        unrealized = float(row["unrealized_pnl"] or 0)
        return KillSwitchStatus(
            active=active,
            tripped_today=bool(row["kill_switch_tripped"]),
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            day_pnl=realized + unrealized,
            loss_limit=float(row["max_loss_limit"] or 0),
            starting_capital=float(row["starting_capital"] or 0),
        )

    async def check_and_maybe_trip(self) -> KillSwitchStatus:
        st = await self.status()
        if not st.active and st.loss_limit < 0 and st.day_pnl <= st.loss_limit:
            await self._trip(st)
            st.active = True
            st.tripped_today = True
        return st

    async def _trip(self, st: KillSwitchStatus) -> None:
        await set_state(_ACTIVE_KEY, True, "risk")
        await execute(
            "UPDATE daily_pnl SET kill_switch_tripped = true, updated_at = now() "
            "WHERE trade_date = $1 AND mode = $2", today_ist(), await self._ns(),
        )
        log.error("kill_switch_tripped", day_pnl=st.day_pnl, limit=st.loss_limit,
                  flatten=self.flatten_on_trip)
        msg = (f"Day PnL ₹{st.day_pnl:.0f} breached limit ₹{st.loss_limit:.0f}. "
               f"New entries blocked; flatten={self.flatten_on_trip}. Manual reset required.")
        if self.alerter:
            await self.alerter.send_async("KILL SWITCH TRIGGERED", msg)
        try:
            from common.events import publish_event
            await publish_event("alert", {"kind": "killswitch", "message": msg, "severity": "critical"})
        except Exception:
            pass

    async def reset(self) -> None:
        await set_state(_ACTIVE_KEY, False, "operator")
        await execute(
            "UPDATE daily_pnl SET kill_switch_tripped = false, updated_at = now() "
            "WHERE trade_date = $1 AND mode = $2", today_ist(), await self._ns(),
        )
        log.info("kill_switch_reset")

    async def update_pnl(self, realized: float | None = None, unrealized: float | None = None) -> None:
        sets, args, idx = [], [today_ist(), await self._ns()], 3
        if realized is not None:
            sets.append(f"realized_pnl = ${idx}"); args.append(realized); idx += 1
        if unrealized is not None:
            sets.append(f"unrealized_pnl = ${idx}"); args.append(unrealized); idx += 1
        if not sets:
            return
        await execute(
            f"UPDATE daily_pnl SET {', '.join(sets)}, updated_at = now() "
            "WHERE trade_date = $1 AND mode = $2", *args,
        )
