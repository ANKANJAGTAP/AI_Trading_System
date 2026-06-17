"""Triple-barrier labeling (López de Prado) — pure, no I/O (§4 #27).

The naive ML label "sign of the next-bar return" is dishonest: it ignores the path
and the holding horizon. The triple-barrier method labels each event by which of
three barriers the forward price path touches FIRST:

    +1  profit-take barrier hit   (a clean winner)
    -1  stop barrier hit          (a clean loser)
     0  vertical (time) barrier   (neither hit within max_holding -> timeout)

This is the honest target the meta-labeler should learn (does this signal reach its
reward before its risk, within the horizon?) instead of an arbitrary next-bar sign.
When a single bar straddles both the stop and the target, the STOP wins
(conservative) — the same worst-case assumption the backtest fill model makes.

`side` is the position side: BUY (long) profits when price rises to the profit
barrier; SELL (short) profits when price falls to it.
"""
from __future__ import annotations


def triple_barrier_label(highs_fwd, lows_fwd, entry_price: float, side: str = "BUY",
                         *, pt_pct: float, sl_pct: float, max_holding: int) -> dict:
    """Label one event from the forward bars AFTER entry (index 0 = first bar after
    the entry bar). `pt_pct`/`sl_pct` are fractional barrier distances from entry.

    Returns {label, barrier, holding, exit_price}: label in {+1,-1,0};
    barrier in {"pt","sl","vertical"}; holding = bars held (1-based; 0 if no data)."""
    e = float(entry_price)
    if side == "BUY":
        pt_level, sl_level = e * (1 + pt_pct), e * (1 - sl_pct)
    else:                                   # short: profit on a fall, stop on a rise
        pt_level, sl_level = e * (1 - pt_pct), e * (1 + sl_pct)

    horizon = min(int(max_holding), len(highs_fwd))
    for i in range(horizon):
        h, l = float(highs_fwd[i]), float(lows_fwd[i])
        if side == "BUY":
            hit_sl, hit_pt = l <= sl_level, h >= pt_level
        else:
            hit_sl, hit_pt = h >= sl_level, l <= pt_level
        if hit_sl:                          # stop first on a same-bar straddle (conservative)
            return {"label": -1, "barrier": "sl", "holding": i + 1,
                    "exit_price": round(sl_level, 4)}
        if hit_pt:
            return {"label": 1, "barrier": "pt", "holding": i + 1,
                    "exit_price": round(pt_level, 4)}
    return {"label": 0, "barrier": "vertical", "holding": horizon, "exit_price": None}


def barrier_to_meta_label(barrier_label: int) -> int:
    """Meta-label for the model: 1 if the profit target was hit first (+1), else 0
    (stop hit, or timed out at the vertical barrier). The honest "was this signal
    worth taking?" target — path- and horizon-aware, independent of how the live
    exit actually played out."""
    return 1 if barrier_label == 1 else 0


def label_events(highs, lows, events, *, pt_pct: float, sl_pct: float,
                 max_holding: int) -> list[dict]:
    """Label a batch of events against one OHLC series. `events` is a list of dicts
    with {"idx": entry_bar_index, "side": "BUY"/"SELL", "entry": entry_price}. Each
    event is labeled on the bars strictly AFTER its entry index (no look-ahead)."""
    out = []
    n = len(highs)
    for ev in events:
        i = int(ev["idx"])
        res = triple_barrier_label(
            highs[i + 1:n], lows[i + 1:n], float(ev["entry"]),
            ev.get("side", "BUY"), pt_pct=pt_pct, sl_pct=sl_pct, max_holding=max_holding)
        out.append({**ev, **res})
    return out
