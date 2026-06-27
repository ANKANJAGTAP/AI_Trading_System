"""Confluence-breakout strategy — backtest + K-sweep + forward-OOS (offline research).

Hypothesis (yours): require K of N independent technical signals to AGREE a breakout is
real before entering. This builds that as a backtestable long-only intraday strategy on
the real 5-min bars, sweeps the confirmation threshold K through the SAME overfitting gate
(Deflated Sharpe + PBO) that validated the F&O book, and reports forward-OOS per K — so we
learn whether confluence has an edge instead of assuming it.

Signal panel (N=10, each a per-bar boolean):
  breakout (20-bar Donchian high) · RVOL surge · EMA20>EMA50 stack · RSI>55 · MACD>0 ·
  Bollinger-upper break · above intraday VWAP · bullish bar · close in upper half · range
  expansion.  confluence = how many fired this bar; enter long when confluence >= K.

Exit: ATR stop (gap-aware, stop-first), R-multiple target, and EOD square-off (intraday).
Costs are modelled (round-trip bps on notional) — the ORB lesson: gross != net.

    sudo docker compose exec -T api python scripts/confluence_breakout.py \
        --from 2025-07-01 --to 2026-06-20 --k-values 4,5,6,7,8 [--mode fade] [--min-rvol 3]

Modes: breakout (long the break) or fade (short it, bet it reverts). --min-rvol gates on
'in-play' intensity. Single-name research harness — a validated verdict, not live wiring.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SYMBOLS = ["NSE:RELIANCE", "NSE:TCS", "NSE:INFY", "NSE:HDFCBANK", "NSE:ICICIBANK",
           "NSE:SBIN", "NSE:LT", "NSE:ITC", "NSE:AXISBANK", "NSE:KOTAKBANK"]
N_SIGNALS = 10


# ---- pure: signal panel + per-symbol backtest (no DB) -----------------------
def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV (ts-indexed) -> frame + `confluence` (0..10), `atr`, and intraday bookkeeping.
    Pure (pandas). All indicators are causal (no look-ahead)."""
    o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]
    out = df.copy()
    out["day"] = pd.DatetimeIndex(out.index).normalize()        # Indian session shares one UTC date
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    macd_hist = macd - macd.ewm(span=9, adjust=False).mean()
    sma20 = c.rolling(20).mean()
    bb_up = sma20 + 2 * c.rolling(20).std()
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    out["atr"] = tr.rolling(14).mean()
    tp = (h + l + c) / 3.0
    out["vwap"] = (tp * v).groupby(out["day"]).cumsum() / v.groupby(out["day"]).cumsum().replace(0, np.nan)
    rng = h - l

    sig = pd.DataFrame(index=df.index)
    sig["breakout"] = c > h.rolling(20).max().shift(1)
    sig["rvol"] = v > 1.5 * v.rolling(20).mean()
    sig["ema_stack"] = (c > ema20) & (ema20 > ema50)
    sig["rsi_mom"] = _rsi(c) > 55
    sig["macd_pos"] = macd_hist > 0
    sig["bb_break"] = c > bb_up
    sig["vwap_above"] = c > out["vwap"]
    sig["bull_bar"] = c > o
    sig["close_strong"] = c > (h + l) / 2.0
    sig["range_exp"] = rng > 1.2 * rng.rolling(20).mean()

    out["confluence"] = sig.fillna(False).astype(int).sum(axis=1)
    out["bars_left"] = out.groupby("day").cumcount(ascending=False)   # 0 on the last bar of the day
    out["rvol_ratio"] = (v / v.rolling(20).mean()).fillna(0.0)        # "in play" intensity gate
    return out


def backtest_symbol(s: pd.DataFrame, k: int, atr_mult: float, reward_r: float,
                    cost_bps: float, capital: float, mode: str = "breakout",
                    min_rvol: float = 0.0, min_bars_left: int = 6) -> list[dict]:
    """Walk bars: when confluence>=k (flat, not near EOD, rvol>=min_rvol) take the trade —
    LONG in 'breakout' mode, SHORT in 'fade' mode (bet the up-break reverts). Exit on
    gap-aware ATR stop (stop-first), R-target, or EOD square-off. Returns [{ts, pnl}]. Pure."""
    short = mode == "fade"
    trades: list[dict] = []
    pos = None
    idx = s.index
    conf = s["confluence"].to_numpy()
    atr = s["atr"].to_numpy()
    bl = s["bars_left"].to_numpy()
    rvr = s["rvol_ratio"].to_numpy()
    O, H, L, C = (s[x].to_numpy() for x in ("open", "high", "low", "close"))
    cost = capital * cost_bps / 10000.0
    for i in range(len(idx)):
        if pos is not None:
            ex = None
            if not short:                              # LONG: stop below, target above
                if O[i] <= pos["stop"]:
                    ex = O[i]                          # gap through stop -> fill at open
                elif L[i] <= pos["stop"]:
                    ex = pos["stop"]                   # stop-first (conservative)
                elif H[i] >= pos["target"]:
                    ex = pos["target"]
                elif bl[i] == 0:
                    ex = C[i]                          # EOD square-off
            else:                                      # SHORT (fade): stop above, target below
                if O[i] >= pos["stop"]:
                    ex = O[i]                          # gap through stop -> fill at open
                elif H[i] >= pos["stop"]:
                    ex = pos["stop"]
                elif L[i] <= pos["target"]:
                    ex = pos["target"]
                elif bl[i] == 0:
                    ex = C[i]
            if ex is not None:
                qty = capital / pos["entry"]
                sgn = -1.0 if short else 1.0
                trades.append({"ts": pos["ts"], "pnl": round(sgn * (ex - pos["entry"]) * qty - cost, 2)})
                pos = None
        if pos is None and bl[i] >= min_bars_left and conf[i] >= k and atr[i] > 0 and rvr[i] >= min_rvol:
            entry = C[i]
            risk = atr_mult * atr[i]
            stop = entry + risk if short else entry - risk
            target = entry - reward_r * risk if short else entry + reward_r * risk
            pos = {"entry": entry, "stop": stop, "target": target, "ts": idx[i]}
    return trades


def split_net(trades: list[dict], mid: dt.date) -> tuple[float, float]:
    """(in-sample net, out-of-sample net) split by entry date at `mid`. Pure."""
    is_n = sum(t["pnl"] for t in trades if str(t["ts"])[:10] < mid.isoformat())
    oos_n = sum(t["pnl"] for t in trades if str(t["ts"])[:10] >= mid.isoformat())
    return round(is_n, 0), round(oos_n, 0)


# ---- offline runner (DB imports deferred) -----------------------------------
async def _run(args) -> int:
    from data.instruments import get_token
    from data.store import load_candles_range_df
    from common.db import close_pool, init_pool
    from backtest.sweep import report_from_results

    try:
        from_dt = dt.date.fromisoformat(args.from_date)
        to_dt = dt.date.fromisoformat(args.to_date)
    except ValueError:
        print("ERROR: --from/--to must be YYYY-MM-DD")
        return 2
    ks = [int(x) for x in args.k_values.split(",") if x.strip()]
    if len(ks) < 2:
        print("ERROR: give >= 2 K values to sweep (PBO compares configs)")
        return 2
    mid = from_dt + (to_dt - from_dt) / 2

    await init_pool()
    per_symbol: dict[str, pd.DataFrame] = {}
    try:
        for sym in args.symbols:
            tok = await get_token(sym)
            if not tok:
                print(f"[skip] {sym}: no instrument_token")
                continue
            df = await load_candles_range_df(tok, args.interval, from_dt, to_dt)
            if len(df) < 100:
                print(f"[skip] {sym}: only {len(df)} {args.interval} bars")
                continue
            per_symbol[sym] = compute_signals(df)
    finally:
        await close_pool()
    if not per_symbol:
        print("no symbols had data — check the interval/backfill")
        return 1

    print(f"confluence {args.mode}: {len(per_symbol)} symbols · {args.interval} · {from_dt}..{to_dt}  "
          f"(OOS split @ {mid.isoformat()}) · K in {ks} · min_rvol={args.min_rvol}")
    results: dict[str, dict] = {}
    for k in ks:
        trades: list[dict] = []
        for sdf in per_symbol.values():
            trades += backtest_symbol(sdf, k, args.atr_mult, args.reward_r, args.cost_bps,
                                      args.capital, mode=args.mode, min_rvol=args.min_rvol)
        results[f"K={k}"] = {"trades": trades}
        net = sum(t["pnl"] for t in trades)
        wins = sum(1 for t in trades if t["pnl"] > 0)
        is_n, oos_n = split_net(trades, mid)
        wr = (wins / len(trades) * 100) if trades else 0.0
        print(f"[K={k}] trades={len(trades):5d}  net={net:>13.0f}  win%={wr:5.1f}  "
              f"IS={is_n:>12.0f}  OOS={oos_n:>12.0f}")

    report = report_from_results(results, args.capital, n_splits=args.n_splits)
    report["trades_per_config"] = {k: len(v["trades"]) for k, v in results.items()}
    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"confluence_{args.mode}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print("\n=== K-sweep verdict (Deflated Sharpe + PBO) ===")
    for key in ("configs", "periods", "best_config", "best_sharpe", "best_psr",
                "deflated_sharpe", "pbo", "verdict"):
        print(f"  {key}: {report.get(key)}")
    print(f"saved: {out}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbols", nargs="+", default=SYMBOLS)
    p.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    p.add_argument("--interval", default="5m")
    p.add_argument("--k-values", dest="k_values", default="4,5,6,7,8", help="confirmation thresholds to sweep")
    p.add_argument("--mode", choices=["breakout", "fade"], default="breakout",
                   help="breakout = long the break; fade = short it (bet it reverts)")
    p.add_argument("--min-rvol", dest="min_rvol", type=float, default=0.0,
                   help="require bar volume >= this x 20-bar avg to enter (0 = off; ~3 = 'in play')")
    p.add_argument("--atr-mult", dest="atr_mult", type=float, default=1.5, help="stop = entry - atr_mult*ATR")
    p.add_argument("--reward-r", dest="reward_r", type=float, default=2.0, help="target = entry + reward_r*risk")
    p.add_argument("--cost-bps", dest="cost_bps", type=float, default=10.0, help="round-trip cost, bps of notional")
    p.add_argument("--capital", type=float, default=100000.0, help="notional per trade")
    p.add_argument("--n-splits", dest="n_splits", type=int, default=10)
    p.add_argument("--out-dir", dest="out_dir", default="backtest_sweeps")
    raise SystemExit(asyncio.run(_run(p.parse_args())))


if __name__ == "__main__":
    main()
