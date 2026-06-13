"""
Structure selection — turn a routed family + the live chain into a concrete,
defined-risk multi-leg Structure (Pillar 4 instruments), priced from the chain.
Naked selling is never produced: every credit structure has a bought wing.
"""
from __future__ import annotations

import numpy as np

from fno_backtest.instruments import (
    Leg, Structure, bull_call_spread, bear_put_spread, iron_condor,
)


def _nearest(chain, opt_type, target):
    sub = chain[chain["opt_type"] == opt_type]
    if sub.empty:
        return None
    strikes = sub["strike"].to_numpy()
    return float(strikes[np.argmin(np.abs(strikes - target))])


def _price(chain, opt_type, strike):
    sub = chain[(chain["opt_type"] == opt_type) & (chain["strike"] == strike)]
    return float(sub["close"].iloc[0]) if not sub.empty else None


def select_structure(family, chain, spot, lot_size, step=50.0,
                     width_steps=2, wing_steps=2):
    """Build a 1-lot Structure (qty=lot_size) for `family`, or None if the
    needed strikes/prices aren't in the chain."""
    w = width_steps * step
    wing = wing_steps * step
    atm = _nearest(chain, "CE", spot)
    if atm is None:
        return None

    def ce(k):
        kk = _nearest(chain, "CE", k)
        return (kk, _price(chain, "CE", kk)) if kk is not None else (None, None)

    def pe(k):
        kk = _nearest(chain, "PE", k)
        return (kk, _price(chain, "PE", kk)) if kk is not None else (None, None)

    if family == "bull_call_debit":
        klo, plo = ce(atm)
        khi, phi = ce(atm + w)
        if None in (plo, phi) or khi <= klo:
            return None
        return bull_call_spread(klo, khi, lot_size, plo, phi)

    if family == "bear_put_debit":
        khi, phi = pe(atm)
        klo, plo = pe(atm - w)
        if None in (phi, plo) or klo >= khi:
            return None
        return bear_put_spread(khi, klo, lot_size, phi, plo)

    if family == "bull_put_credit":
        ks, ps = pe(atm - w)          # short (sell)
        kl, pl = pe(atm - w - wing)   # long wing (buy, farther OTM)
        if None in (ps, pl) or kl >= ks:
            return None
        return Structure("bull_put_credit", [
            Leg("PE", ks, "SELL", lot_size, ps),
            Leg("PE", kl, "BUY", lot_size, pl),
        ])

    if family == "bear_call_credit":
        ks, ps = ce(atm + w)          # short (sell)
        kl, pl = ce(atm + w + wing)   # long wing (buy, farther OTM)
        if None in (ps, pl) or kl <= ks:
            return None
        return Structure("bear_call_credit", [
            Leg("CE", ks, "SELL", lot_size, ps),
            Leg("CE", kl, "BUY", lot_size, pl),
        ])

    if family == "iron_condor":
        ps_k, ps_p = pe(atm - w)
        pl_k, pl_p = pe(atm - w - wing)
        cs_k, cs_p = ce(atm + w)
        cl_k, cl_p = ce(atm + w + wing)
        if None in (ps_p, pl_p, cs_p, cl_p):
            return None
        return iron_condor(pl_k, ps_k, cs_k, cl_k, lot_size, pl_p, ps_p, cs_p, cl_p)

    return None


def one_lot_max_loss(structure, spot) -> float:
    """Worst-case loss (positive rupees) of the structure over a wide spot range."""
    prof = structure.profile(spot * 0.85, spot * 1.15, n=600)
    return abs(min(prof["max_loss"], 0.0))
