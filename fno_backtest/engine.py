"""
Event-driven, options-aware backtester.

  * simulate_trade  — exact per-structure P&L accounting: entry fills + costs,
    hold to expiry, cash-settle at intrinsic, exit costs (worthless legs lapse
    with no cost). The deterministic core everything else is checked against.
  * EventDrivenBacktester.run — replay a list of trade signals into an equity
    curve + trade log.
  * backtest_strategy — drive the above from canonical EOD chain data and a
    strategy callback (date, chain, spot) -> Structure | None.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .costs import CostConfig, leg_cost
from .instruments import Structure, intrinsic, settlement_pnl


def _opp(side: str) -> str:
    return "SELL" if side.upper() == "BUY" else "BUY"


def simulate_trade(structure: Structure, settle_spot: float,
                   cfg: CostConfig = CostConfig()) -> dict:
    """Net P&L of entering a structure and cash-settling it at expiry."""
    entry_cost = sum(
        leg_cost(leg.entry_price, leg.qty, leg.side, leg.segment, cfg)["total"]
        for leg in structure.legs
    )
    gross = settlement_pnl(structure, settle_spot)

    exit_cost = 0.0
    for leg in structure.legs:
        settle_px = intrinsic(leg.opt_type, leg.strike, settle_spot)
        if leg.opt_type != "FUT" and settle_px <= 0:
            continue                      # OTM option lapses worthless: no exit cost
        exit_cost += leg_cost(settle_px, leg.qty, _opp(leg.side), leg.segment, cfg)["total"]

    costs = entry_cost + exit_cost
    return {
        "name": structure.name,
        "gross": float(gross),
        "entry_cost": float(entry_cost),
        "exit_cost": float(exit_cost),
        "costs": float(costs),
        "net": float(gross - costs),
        "net_premium": float(structure.net_premium()),
    }


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.Series
    starting_capital: float

    def report(self, num_trials: int = 1, bias_audit: dict | None = None) -> dict:
        from .report import build_report
        return build_report(self, num_trials, bias_audit)


class EventDrivenBacktester:
    def __init__(self, starting_capital: float = 1_000_000.0,
                 cfg: CostConfig = CostConfig()):
        self.starting_capital = starting_capital
        self.cfg = cfg

    def run(self, signals: list[dict]) -> BacktestResult:
        """signals: list of {entry_date, exit_date, structure, settle_spot}."""
        equity = self.starting_capital
        rows, curve = [], {}
        for sig in sorted(signals, key=lambda s: s["entry_date"]):
            r = simulate_trade(sig["structure"], sig["settle_spot"], self.cfg)
            equity += r["net"]
            rows.append({
                "entry_date": sig["entry_date"], "exit_date": sig["exit_date"],
                "name": r["name"], "gross": r["gross"], "costs": r["costs"],
                "net": r["net"], "equity": equity,
            })
            curve[sig["exit_date"]] = equity
        trades = pd.DataFrame(rows)
        equity_curve = pd.Series(curve).sort_index() if curve else pd.Series(dtype=float)
        return BacktestResult(trades, equity_curve, self.starting_capital)


def backtest_strategy(eod: pd.DataFrame, underlying: str, strategy_fn,
                      starting_capital: float = 1_000_000.0,
                      cfg: CostConfig = CostConfig()) -> BacktestResult:
    """Drive the backtester from EOD chain data + a strategy callback."""
    from features.engine import underlying_daily_from_eod

    daily = underlying_daily_from_eod(eod, underlying)
    opt = eod[(eod["underlying"] == underlying) & (eod["instrument"] == "OPT")].copy()
    opt["trade_date"] = pd.to_datetime(opt["trade_date"])
    opt["expiry"] = pd.to_datetime(opt["expiry"])

    signals = []
    for date, chain_all in opt.groupby("trade_date"):
        if date not in daily.index:
            continue
        future = chain_all[chain_all["expiry"] >= date]
        if future.empty:
            continue
        front = future["expiry"].min()
        chain = chain_all[chain_all["expiry"] == front]
        spot = float(daily.loc[date, "close"])
        struct = strategy_fn(date, chain, spot)
        if struct is None:
            continue
        on_or_before = daily.index[daily.index <= front]
        settle_date = on_or_before.max() if len(on_or_before) else date
        signals.append({
            "entry_date": date, "exit_date": front,
            "structure": struct, "settle_spot": float(daily.loc[settle_date, "close"]),
        })
    return EventDrivenBacktester(starting_capital, cfg).run(signals)
