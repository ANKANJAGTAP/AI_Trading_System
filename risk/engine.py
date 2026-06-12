"""Risk & Capital Engine (spec §4) — the unbypassable upstream gate.

`size()` gathers live inputs (capital, sleeve utilisation, portfolio open-R, live
margin) and runs the canonical R-sizing algorithm, after enforcing the kill-switch
and max-concurrent-positions gates. Order of ceilings (spec §3): portfolio risk ->
sleeve cap -> live available margin, with live margin the final non-negotiable clamp.
"""
from __future__ import annotations

import time

from common.logging import get_logger
from risk.capital import CapitalReader
from risk.heat import compute_heat
from risk.kill_switch import KillSwitch
from risk.models import InstrumentKind, SizingResult
from risk.positions import (PositionsProvider, deployed_by_sleeve, open_r_by_underlying,
                            open_trades_count, total_open_r)
from risk.sizing import max_concurrent_positions, size_position, size_structure

log = get_logger("risk_engine")

_SLEEVE_PRODUCT = {
    "intraday_stocks": "MIS",
    "swing_stocks": "CNC",
    "fno": "NRML",
    "mcx_commodities": "NRML",
}


def _kind_from_instrument(instrument: dict) -> InstrumentKind:
    itype = (instrument.get("instrument_type") or "").upper()
    if itype in ("CE", "PE"):
        return InstrumentKind.OPTION_BUY
    if itype == "FUT":
        return InstrumentKind.FUTURES
    return InstrumentKind.EQUITY


class RiskEngine:
    def __init__(
        self,
        config,
        capital_reader: CapitalReader | None = None,
        positions_provider: PositionsProvider | None = None,
        kill_switch: KillSwitch | None = None,
        adapter=None,
        governor=None,
        alerter=None,
        mode: str = "simulated_fill",
        per_trade_pct: float | None = None,
    ) -> None:
        self.config = config
        self.capital = capital_reader or CapitalReader(adapter, governor)
        self.positions = positions_provider or PositionsProvider()
        self.adapter = adapter
        self.governor = governor
        self.mode = mode
        self._per_trade_pct = per_trade_pct   # paper overlay; None -> spec default
        self.kill_switch = kill_switch or KillSwitch(config, mode, alerter)
        self._vscale: float = 1.0             # cached India-VIX size scalar
        self._vscale_ts: float = 0.0

    def _per_trade(self) -> float:
        return self._per_trade_pct or self.config.risk.per_trade_risk_pct.default

    async def _vol_scale(self) -> float:
        """India-VIX size scalar (config `risk.vol_scaling`): full size at/below the
        reference VIX, shrinking proportionally above it (ref/VIX, floored at
        min_scale). Positions sized for calm regimes get force-liquidated in storms —
        constant-vol targeting cuts drawdowns where they actually happen. Cached for
        5 minutes; fails OPEN to 1.0 when VIX is unavailable."""
        vs = getattr(self.config.risk, "vol_scaling", {}) or {}
        if not vs.get("enabled", False):
            return 1.0
        now = time.monotonic()
        if self._vscale_ts and now - self._vscale_ts < 300:
            return self._vscale
        scale = 1.0
        try:
            from data.instruments import get_token
            from data.store import load_candles_df
            tok = await get_token("NSE:INDIA VIX")
            if tok:
                df = await load_candles_df(tok, "day", 1)
                vix = float(df["close"].iloc[-1]) if df is not None and len(df) else 0.0
                ref = float(vs.get("reference_vix", 15.0) or 15.0)
                floor = float(vs.get("min_scale", 0.4) or 0.4)
                if vix > ref > 0:
                    scale = max(floor, ref / vix)
                    log.info("vol_scaled_sizing", vix=round(vix, 2), scale=round(scale, 3))
        except Exception as exc:
            log.warning("vol_scale_unavailable_fail_open", error=str(exc))
        self._vscale, self._vscale_ts = scale, now
        return scale

    async def _active_brake(self, sleeve: str) -> str | None:
        """Period / activity brakes evaluated by the engine's manage loop (config
        `risk.period_brakes` / `risk.trade_brakes`). Like the kill switch, they only
        block NEW entries — open positions stay managed."""
        from common.market_time import today_ist
        from common.state import get_state
        pb = await get_state("period_brake_active")
        if pb:
            return f"period brake active ({pb.get('scope')} {pb.get('period')})"
        today = str(today_ist())
        tb = await get_state("trade_budget_exhausted")
        if tb and tb.get("date") == today:
            return f"daily trade budget exhausted ({tb.get('trades')})"
        sb = await get_state(f"sleeve_{sleeve}_brake")
        if sb and sb.get("date") == today:
            return f"{sleeve} loss-streak brake (stood down for today)"
        return None

    # --- ceilings ---------------------------------------------------------
    def _sleeve_remaining(self, sleeve: str, capital: float, positions: list[dict]) -> float | None:
        sc = self.config.sleeves.sleeves.get(sleeve)
        if not sc:
            return None
        cap_rupees = sc.cap_pct / 100.0 * capital
        return max(0.0, cap_rupees - deployed_by_sleeve(positions).get(sleeve, 0.0))

    def _portfolio_remaining_r(self, capital: float, positions: list[dict]) -> float:
        pr = self.config.risk.portfolio_risk_limit_pct.default / 100.0 * capital
        return max(0.0, pr - total_open_r(positions))

    async def _margin_per_unit(self, instrument: dict, entry: float, side: str, sleeve: str, lot_size: int):
        """Best-effort live margin per unit via order_margins (requires funded RMS).
        Returns margin_per_unit or None if unavailable (pre-activation)."""
        if not (self.adapter and self.governor):
            return None
        order = {
            "exchange": instrument.get("exchange"),
            "tradingsymbol": instrument.get("tradingsymbol"),
            "transaction_type": side,
            "variety": "regular",
            "product": _SLEEVE_PRODUCT.get(sleeve, "MIS"),
            "order_type": "MARKET",
            "quantity": max(1, lot_size),
            "price": 0,
        }
        try:
            res = await self.governor.call("other", self.adapter.order_margins, [order])
            total = float(res[0].get("total")) if res else 0.0
            if total > 0:
                return total / max(1, lot_size)
        except Exception as exc:
            log.warning("order_margins_unavailable", error=str(exc))
        return None

    # --- public API (Appendix B) -----------------------------------------
    async def size(self, entry: float, stop: float, instrument: dict, sleeve: str,
                   confidence: float = 1.0, side: str = "BUY") -> SizingResult:
        if await self.kill_switch.is_active():
            return SizingResult.reject("kill-switch active: new entries blocked")
        brake = await self._active_brake(sleeve)
        if brake:
            return SizingResult.reject(brake)

        capital = await self.capital.get_capital()
        if capital <= 0:
            return SizingResult.reject("no live capital (account funds/segment pending activation)")

        positions = await self.positions.open_positions()
        maxc = max_concurrent_positions(
            self.config.risk.portfolio_risk_limit_pct.default,
            self._per_trade(),
        )
        # Count TRADES (structures = 1), not leg rows.
        n_open = open_trades_count(positions)
        if n_open >= maxc:
            return SizingResult.reject(f"max concurrent positions reached ({n_open}/{maxc})")

        # One position per instrument: a setup that persists across slow-loop cycles
        # must not stack duplicate entries on the same name (today's tape: NESTLEIND
        # and DRREDDY both entered twice one minute apart). Re-entry happens after
        # the position closes (and its cooldown expires) — never alongside it.
        tok = instrument.get("instrument_token")
        if tok and any(p.get("instrument_token") == tok for p in positions):
            return SizingResult.reject("already in a position on this instrument")

        kind = _kind_from_instrument(instrument)
        lot_size = int(instrument.get("lot_size") or 1) if kind is not InstrumentKind.EQUITY else 1
        margin_per_unit = await self._margin_per_unit(instrument, entry, side, sleeve, lot_size)

        # Live-margin clamp uses REMAINING free capital (total minus already-deployed),
        # so concurrent positions don't each size against the full account.
        deployed = sum(deployed_by_sleeve(positions).values())
        margin_available = max(0.0, capital - deployed) if margin_per_unit else None

        return size_position(
            capital=capital,
            # vol-scaled R: full size in calm vol, proportionally smaller in storms
            per_trade_risk_pct=self._per_trade() * await self._vol_scale(),
            per_instrument_cap_pct=self.config.risk.per_instrument_cap_pct,
            entry_price=entry,
            stop_price=stop,
            lot_size=lot_size,
            kind=kind,
            confidence=confidence,
            sleeve_remaining_capital=self._sleeve_remaining(sleeve, capital, positions),
            portfolio_remaining_r=self._portfolio_remaining_r(capital, positions),
            margin_available=margin_available,
            margin_per_unit=margin_per_unit,
            min_risk_utilization=float(getattr(self.config.risk, "min_risk_utilization", 0.01) or 0),
        )

    async def _structure_margin_per_lot(self, underlying: str | None, expiry, structure: dict | None,
                                        lot_size: int) -> float | None:
        """Best-effort hedge-aware margin for ONE lot of the structure via the broker's
        basket-margin API (resolved legs, real RMS numbers). Returns None when the
        legs can't be resolved or the API is unavailable — fail-open like equity."""
        if not (self.adapter and self.governor and underlying and expiry and structure):
            return None
        try:
            from data.option_chain import resolve_option
            from execution.structures import _legs_from_structure
            orders = []
            for opt, strike, side in _legs_from_structure(structure):
                oi = await resolve_option(underlying, expiry, strike, opt)
                if oi is None:
                    return None
                orders.append({
                    "exchange": "NFO", "tradingsymbol": oi["tradingsymbol"],
                    "transaction_type": side, "variety": "regular", "product": "NRML",
                    "order_type": "MARKET", "quantity": max(1, lot_size), "price": 0,
                })
            res = await self.governor.call("other", self.adapter.basket_order_margins, orders)
            total = float(((res or {}).get("final") or {}).get("total") or 0)
            return total if total > 0 else None
        except Exception as exc:
            log.warning("basket_margins_unavailable", error=str(exc))
            return None

    async def size_structure(self, max_loss_per_lot: float, lot_size: int, sleeve: str,
                             confidence: float = 1.0, margin_per_lot: float | None = None,
                             underlying: str | None = None, expiry=None,
                             structure: dict | None = None) -> SizingResult:
        if await self.kill_switch.is_active():
            return SizingResult.reject("kill-switch active: new entries blocked")
        brake = await self._active_brake(sleeve)
        if brake:
            return SizingResult.reject(brake)
        capital = await self.capital.get_capital()
        if capital <= 0:
            return SizingResult.reject("no live capital (account funds/segment pending activation)")
        positions = await self.positions.open_positions()

        # Structures must respect max-concurrent too (as trades, not legs).
        maxc = max_concurrent_positions(
            self.config.risk.portfolio_risk_limit_pct.default, self._per_trade())
        n_open = open_trades_count(positions)
        if n_open >= maxc:
            return SizingResult.reject(f"max concurrent positions reached ({n_open}/{maxc})")

        # Per-underlying concentration: open R across ALL strikes/structures of this
        # name vs the configured % of capital (stacked strikes = one correlated bet).
        underlying_remaining_r = None
        u_cap_pct = float(getattr(self.config.risk, "per_underlying_risk_pct", 0) or 0)
        if underlying and u_cap_pct > 0:
            u_cap = u_cap_pct / 100.0 * capital
            underlying_remaining_r = max(0.0, u_cap - open_r_by_underlying(positions, underlying))

        # Live margin: real basket margin per lot if resolvable; clamp against
        # REMAINING capital (total minus deployed) AND the sleeve's own cap — the
        # equity path honors sleeve caps, structures must too.
        if margin_per_lot is None:
            margin_per_lot = await self._structure_margin_per_lot(underlying, expiry, structure, lot_size)
        margin_available = None
        if margin_per_lot:
            deployed = sum(deployed_by_sleeve(positions).values())
            margin_available = max(0.0, capital - deployed)
            sleeve_rem = self._sleeve_remaining(sleeve, capital, positions)
            if sleeve_rem is not None:
                margin_available = min(margin_available, sleeve_rem)

        max_lots = int((self.config.strategy.fno or {}).get("max_lots_per_structure", 0) or 0) or None
        return size_structure(
            capital=capital,
            # vol-scaled R: full size in calm vol, proportionally smaller in storms
            per_trade_risk_pct=self._per_trade() * await self._vol_scale(),
            max_loss_per_lot=max_loss_per_lot,
            lot_size=lot_size,
            confidence=confidence,
            portfolio_remaining_r=self._portfolio_remaining_r(capital, positions),
            underlying_remaining_r=underlying_remaining_r,
            margin_available=margin_available,
            margin_per_lot=margin_per_lot,
            max_lots=max_lots,
        )

    async def check_kill_switch(self):
        return await self.kill_switch.check_and_maybe_trip()

    async def portfolio_heat(self):
        capital = await self.capital.get_capital()
        positions = await self.positions.open_positions()
        return await compute_heat(self.config, positions, capital, per_trade_pct=self._per_trade())
