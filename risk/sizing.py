"""Canonical R-unit position sizing (spec §4) — pure, deterministic, testable.

`size_position` implements the spec algorithm for price-stop instruments
(equity / futures / naked option BUY, where the option's stop is on the premium):

    R          = capital * per_trade_risk_pct/100
    effective_R = R * confidence                      (confidence maps size within R)
    risk/unit  = |entry - stop|                        (premium distance for options)
    raw units  = floor(effective_R / risk_per_unit)    rounded down to lot_size
    clamp by   : per-instrument cap -> sleeve cap -> portfolio remaining risk -> live margin
    if < 1 lot/share after clamps -> REJECT

`size_structure` implements defined-risk option structures, where R maps to the
structure's known max loss per lot.
"""
from __future__ import annotations

import math

from risk.models import InstrumentKind, SizingResult


def floor_to_lot(units: float, lot_size: int) -> int:
    if units <= 0:
        return 0
    if lot_size <= 1:
        return int(math.floor(units))
    return int(math.floor(units / lot_size) * lot_size)


def size_position(
    *,
    capital: float,
    per_trade_risk_pct: float,
    per_instrument_cap_pct: float,
    entry_price: float,
    stop_price: float,
    lot_size: int = 1,
    kind: InstrumentKind = InstrumentKind.EQUITY,
    confidence: float = 1.0,
    sleeve_remaining_capital: float | None = None,
    portfolio_remaining_r: float | None = None,
    margin_available: float | None = None,
    margin_per_unit: float | None = None,
    min_risk_utilization: float = 0.0,
) -> SizingResult:
    confidence = max(0.0, min(1.0, confidence))
    r_rupees = capital * per_trade_risk_pct / 100.0
    effective_r = r_rupees * confidence
    if effective_r <= 0:
        return SizingResult.reject("no risk budget (capital or confidence is zero)")

    risk_per_unit = abs(entry_price - stop_price)
    if risk_per_unit <= 0:
        return SizingResult.reject("invalid stop (zero distance to entry)")
    if entry_price <= 0:
        return SizingResult.reject("invalid entry price")

    units = floor_to_lot(effective_r / risk_per_unit, lot_size)
    # Capital allocated per unit: price for equity/futures notional, premium for options.
    price_per_unit = entry_price
    clamps: list[str] = []

    def apply(limit_units: int, label: str) -> None:
        nonlocal units
        if limit_units < units:
            units = limit_units
            clamps.append(label)

    # (1) per-instrument cap
    apply(floor_to_lot((per_instrument_cap_pct / 100.0 * capital) / price_per_unit, lot_size),
          "per_instrument_cap")
    # (2) sleeve remaining capital
    if sleeve_remaining_capital is not None:
        apply(floor_to_lot(max(0.0, sleeve_remaining_capital) / price_per_unit, lot_size),
              "sleeve_cap")
    # (3) portfolio remaining open-R
    if portfolio_remaining_r is not None:
        apply(floor_to_lot(max(0.0, portfolio_remaining_r) / risk_per_unit, lot_size),
              "portfolio_risk")
    # (4) live available margin (final, non-negotiable clamp)
    if margin_available is not None and margin_per_unit:
        apply(floor_to_lot(max(0.0, margin_available) / margin_per_unit, lot_size),
              "live_margin")

    if units < max(1, lot_size):
        return SizingResult.reject(
            "size below 1 lot/share after clamps", clamps=clamps,
            r_intended=effective_r, lot_size=lot_size,
        )

    # Risk-utilization floor: if the clamps leave only a token position (e.g. an
    # exhausted sleeve cap allowing 1 share risking Rs 6 against an intended Rs 20k),
    # the trade is fee-bleed and attention noise — skip it rather than take it.
    if min_risk_utilization > 0 and (units * risk_per_unit) < effective_r * min_risk_utilization:
        return SizingResult.reject(
            f"clamped to {units} units — risk utilization below "
            f"{min_risk_utilization:.0%} of intended R", clamps=clamps,
            r_intended=effective_r, lot_size=lot_size,
        )

    return SizingResult(
        rejected=False,
        quantity=units,
        lots=units // lot_size if lot_size > 1 else units,
        lot_size=lot_size,
        r_intended=effective_r,
        actual_risk=units * risk_per_unit,
        capital_allocated=units * price_per_unit,
        clamps=clamps,
        detail={"kind": kind.value, "risk_per_unit": risk_per_unit, "raw_R": r_rupees},
    )


def size_structure(
    *,
    capital: float,
    per_trade_risk_pct: float,
    max_loss_per_lot: float,
    lot_size: int,
    confidence: float = 1.0,
    portfolio_remaining_r: float | None = None,
    underlying_remaining_r: float | None = None,
    margin_available: float | None = None,
    margin_per_lot: float | None = None,
    max_lots: int | None = None,
) -> SizingResult:
    """Defined-risk structure: R maps to the structure's known max loss per lot."""
    confidence = max(0.0, min(1.0, confidence))
    effective_r = capital * per_trade_risk_pct / 100.0 * confidence
    if effective_r <= 0:
        return SizingResult.reject("no risk budget (capital or confidence is zero)")
    if max_loss_per_lot <= 0:
        return SizingResult.reject("structure max-loss must be finite and positive")

    lots = int(math.floor(effective_r / max_loss_per_lot))
    clamps: list[str] = []

    def apply(limit_lots: int, label: str) -> None:
        nonlocal lots
        if limit_lots < lots:
            lots = limit_lots
            clamps.append(label)

    if portfolio_remaining_r is not None:
        apply(int(math.floor(max(0.0, portfolio_remaining_r) / max_loss_per_lot)), "portfolio_risk")
    # Concentration: total open R on ONE underlying across all strikes/structures —
    # stacking strikes of the same name can't bypass the cap.
    if underlying_remaining_r is not None:
        apply(int(math.floor(max(0.0, underlying_remaining_r) / max_loss_per_lot)), "underlying_cap")
    if margin_available is not None and margin_per_lot:
        apply(int(math.floor(max(0.0, margin_available) / margin_per_lot)), "live_margin")
    if max_lots is not None and max_lots > 0:
        apply(max_lots, "max_lots_per_structure")   # concentration cap (no oversized single structure)

    if lots < 1:
        return SizingResult.reject(
            "size below 1 lot after clamps", clamps=clamps, r_intended=effective_r, lot_size=lot_size
        )

    return SizingResult(
        rejected=False,
        quantity=lots * lot_size,
        lots=lots,
        lot_size=lot_size,
        r_intended=effective_r,
        actual_risk=lots * max_loss_per_lot,
        capital_allocated=lots * max_loss_per_lot,
        clamps=clamps,
        detail={"kind": InstrumentKind.STRUCTURE.value, "max_loss_per_lot": max_loss_per_lot},
    )


def max_concurrent_positions(portfolio_risk_limit_pct: float, per_trade_risk_pct: float) -> int:
    if per_trade_risk_pct <= 0:
        return 0
    return int(portfolio_risk_limit_pct // per_trade_risk_pct)
