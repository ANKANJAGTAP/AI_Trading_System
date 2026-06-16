"""Live capital reader (spec §3/§5): capital is read live from Kite margins each
session and everything is sized as a % of it. Sums available cash across the
equity and commodity segments. Supports a static override for tests/paper.

Paper compounding (`risk.paper_compound`): the static base is adjusted by the
cumulative realized P&L, so sizing follows the RUNNING balance the daily equity
report tracks (10L + profits − losses), exactly like live capital would.
"""
from __future__ import annotations

from common.logging import get_logger

log = get_logger("capital")


class CapitalReader:
    def __init__(self, adapter=None, governor=None, static_capital: float | None = None,
                 compound: bool = False, mode_provider=None) -> None:
        self.adapter = adapter
        self.governor = governor
        self.static_capital = static_capital
        self.compound = compound
        # P0#1: async () -> RuntimeModeState. When the active mode says
        # capital_source == broker_live, the paper static is ignored and capital is
        # read live from broker margins — so a flip to live can't size on paper money.
        self.mode_provider = mode_provider
        self._cache: float | None = None

    @staticmethod
    def _segment_available(margins: dict) -> float:
        if not isinstance(margins, dict):
            return 0.0
        net = margins.get("net")
        if net is None:
            net = (margins.get("available") or {}).get("live_balance")
        try:
            return float(net or 0.0)
        except (TypeError, ValueError):
            return 0.0

    async def get_capital(self, refresh: bool = False) -> float:
        use_static = self.static_capital is not None
        if use_static and self.mode_provider is not None:
            try:
                state = await self.mode_provider()
                if getattr(state, "use_broker_capital", False):
                    use_static = False        # live: read broker margins, not paper static
            except Exception as exc:
                log.warning("capital_mode_check_failed_using_static", error=str(exc))
        if use_static:
            base = float(self.static_capital)
            if not self.compound:
                return base
            if self._cache is not None and not refresh:
                return self._cache
            try:
                from common.db import fetchval
                realized = float(await fetchval(
                    "SELECT COALESCE(SUM(realized_pnl),0) FROM positions WHERE status='closed'") or 0)
            except Exception as exc:
                log.warning("compound_capital_read_failed", error=str(exc))
                realized = 0.0
            self._cache = max(0.0, base + realized)
            return self._cache
        if self._cache is not None and not refresh:
            return self._cache
        total = 0.0
        for segment in ("equity", "commodity"):
            try:
                margins = await self.governor.call("other", self.adapter.margins, segment)
                total += self._segment_available(margins)
            except Exception as exc:
                log.warning("margins_segment_unavailable", segment=segment, error=str(exc))
        self._cache = total
        log.info("capital_read", total=total)
        return total
