"""OCO/GTT bracket creation (spec §8).

Sim mode arms a fast-loop guard (price levels monitored locally). Live mode places
a Kite GTT-OCO (stop + target) AND arms the guard as a backstop. The exit legs are
sized to the ACTUALLY filled quantity, so partial fills are bracket-safe.
"""
from __future__ import annotations

from common.logging import get_logger
from execution.guards import Guard

log = get_logger("brackets")


def dynamic_exit_cfg(config, sleeve: str) -> dict:
    """Per-sleeve dynamic-exit knobs (MCX reuses the intraday parameters)."""
    if sleeve in ("intraday_stocks", "mcx_commodities"):
        return (config.strategy.intraday_stocks.get("dynamic_exit") or {})
    return {}


async def create_bracket(executor, decision, fill, position_id: int, mode: str) -> dict:
    dyn = dynamic_exit_cfg(executor.config, decision.sleeve)
    executor.guards.arm(Guard(
        position_id=position_id, side=decision.side, entry=fill.price,
        stop=decision.stop_price, target=decision.target_price,
        instrument_token=decision.instrument.get("instrument_token", 0),
        square_off=executor.square_off_time(decision.sleeve),
        breakeven_at_r=float(dyn.get("breakeven_at_r", 0) or 0),
        lock_trigger_frac=float(dyn.get("lock_trigger_frac", 0) or 0),
        max_giveback_frac=float(dyn.get("max_giveback_frac", 0.35) or 0.35),
        init_risk=abs(float(fill.price) - float(decision.stop_price or 0)),
    ))
    bracket = {"type": "guard", "mode": mode, "stop": decision.stop_price,
               "target": decision.target_price, "quantity": fill.quantity}

    if mode == "live" and decision.stop_price and decision.target_price:
        exit_side = "SELL" if decision.side == "BUY" else "BUY"
        lower, upper = sorted([decision.stop_price, decision.target_price])

        def leg(price: float) -> dict:
            return {
                "exchange": decision.instrument["exchange"],
                "tradingsymbol": decision.instrument["tradingsymbol"],
                "transaction_type": exit_side, "quantity": fill.quantity,
                "order_type": "LIMIT", "product": decision.product, "price": price,
            }

        try:
            gtt_id = await executor.governor.call(
                "order", executor.adapter.place_oco,
                tradingsymbol=decision.instrument["tradingsymbol"],
                exchange=decision.instrument["exchange"], last_price=fill.price,
                lower_trigger=lower, upper_trigger=upper, orders=[leg(lower), leg(upper)])
            bracket = {"type": "gtt_oco", "mode": "live", "gtt_id": gtt_id,
                       "stop": decision.stop_price, "target": decision.target_price,
                       "quantity": fill.quantity}
            # Persist the gtt_id so close()/safe-exit can cancel the resting OCO
            # instead of leaving it to re-fire into a new naked position.
            try:
                await executor.book.attach_bracket(position_id, bracket)
            except Exception as exc:
                log.error("attach_bracket_failed", error=str(exc))
        except Exception as exc:
            log.error("gtt_bracket_failed", error=str(exc))  # guard still protects
    return bracket
