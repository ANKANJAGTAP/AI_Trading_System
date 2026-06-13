"""
Options analytics — Black-Scholes greeks, implied vol, and option-chain features.

Two layers:
  * scalar BS math (price/greeks/IV) — implemented directly, matching the repo's
    documented formulas; no SciPy dependency.
  * chain features — given an option-chain snapshot (canonical EOD rows for one
    underlying/expiry) plus the spot and time-to-expiry, compute PCR, max-pain,
    net GEX, ATM IV, and skew. IV/greeks are SOLVED FROM PRICES (bhavcopy gives
    no IV), which is the realistic, point-in-time path.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

SQRT2 = math.sqrt(2.0)
SQRT2PI = math.sqrt(2.0 * math.pi)


# --------------------------------------------------------------------------- #
# scalar Black-Scholes
# --------------------------------------------------------------------------- #
def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT2))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT2PI


def _d1_d2(S, K, t, r, sigma):
    v = sigma * math.sqrt(t)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * t) / v
    return d1, d1 - v


def bs_price(S, K, t, r, sigma, opt="CE") -> float:
    if t <= 0 or sigma <= 0:
        return max(S - K, 0.0) if opt == "CE" else max(K - S, 0.0)
    d1, d2 = _d1_d2(S, K, t, r, sigma)
    if opt == "CE":
        return S * norm_cdf(d1) - K * math.exp(-r * t) * norm_cdf(d2)
    return K * math.exp(-r * t) * norm_cdf(-d2) - S * norm_cdf(-d1)


def bs_delta(S, K, t, r, sigma, opt="CE") -> float:
    if t <= 0 or sigma <= 0:
        return 0.0
    d1, _ = _d1_d2(S, K, t, r, sigma)
    return norm_cdf(d1) if opt == "CE" else norm_cdf(d1) - 1.0


def bs_gamma(S, K, t, r, sigma) -> float:
    if t <= 0 or sigma <= 0:
        return 0.0
    d1, _ = _d1_d2(S, K, t, r, sigma)
    return norm_pdf(d1) / (S * sigma * math.sqrt(t))


def bs_vega(S, K, t, r, sigma) -> float:
    """Vega per 1 percentage-point change in IV."""
    if t <= 0 or sigma <= 0:
        return 0.0
    d1, _ = _d1_d2(S, K, t, r, sigma)
    return S * norm_pdf(d1) * math.sqrt(t) / 100.0


def implied_vol(price, S, K, t, r, opt="CE") -> float:
    """Bisection IV solve (matches the repo's algorithm). Returns 0 if price is
    below intrinsic or expiry is zero."""
    if t <= 0:
        return 0.0
    intrinsic = max(S - K, 0.0) if opt == "CE" else max(K - S, 0.0)
    if price <= intrinsic + 1e-9:
        return 0.0
    lo, hi = 1e-4, 5.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if bs_price(S, K, t, r, mid, opt) - price > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


# --------------------------------------------------------------------------- #
# IV-history transforms (series in -> series/scalar out)
# --------------------------------------------------------------------------- #
def iv_rank(iv_hist: pd.Series) -> float:
    lo, hi = iv_hist.min(), iv_hist.max()
    if hi == lo:
        return float("nan")
    return float((iv_hist.iloc[-1] - lo) / (hi - lo) * 100.0)


def iv_percentile(iv_hist: pd.Series) -> float:
    if len(iv_hist) == 0:
        return float("nan")
    cur = iv_hist.iloc[-1]
    return float((iv_hist < cur).mean() * 100.0)


# --------------------------------------------------------------------------- #
# chain features
# --------------------------------------------------------------------------- #
def enrich_chain(chain: pd.DataFrame, spot: float, t: float, r: float = 0.065) -> pd.DataFrame:
    """Add iv/delta/gamma columns by solving BS from each option's close price.

    `chain` must have columns: opt_type ('CE'/'PE'), strike, close, oi.
    """
    out = chain.copy()
    ivs, deltas, gammas = [], [], []
    for _, row in out.iterrows():
        opt = "CE" if row["opt_type"] == "CE" else "PE"
        iv = implied_vol(row["close"], spot, row["strike"], t, r, opt)
        ivs.append(iv)
        deltas.append(bs_delta(spot, row["strike"], t, r, iv, opt) if iv > 0 else 0.0)
        gammas.append(bs_gamma(spot, row["strike"], t, r, iv) if iv > 0 else 0.0)
    out["iv"] = ivs
    out["delta"] = deltas
    out["gamma"] = gammas
    return out


def pcr_oi(chain: pd.DataFrame) -> float:
    call_oi = chain.loc[chain["opt_type"] == "CE", "oi"].sum()
    put_oi = chain.loc[chain["opt_type"] == "PE", "oi"].sum()
    return float(put_oi / call_oi) if call_oi else float("nan")


def pcr_volume(chain: pd.DataFrame) -> float:
    cv = chain.loc[chain["opt_type"] == "CE", "volume"].sum()
    pv = chain.loc[chain["opt_type"] == "PE", "volume"].sum()
    return float(pv / cv) if cv else float("nan")


def max_pain(chain: pd.DataFrame) -> float:
    """Strike that minimises total option-holder payout at expiry."""
    calls = chain[chain["opt_type"] == "CE"][["strike", "oi"]].to_numpy()
    puts = chain[chain["opt_type"] == "PE"][["strike", "oi"]].to_numpy()
    strikes = np.unique(chain["strike"].to_numpy())
    best_k, best_pain = float("nan"), float("inf")
    for k in strikes:
        call_loss = np.sum(np.clip(k - calls[:, 0], 0, None) * calls[:, 1]) if len(calls) else 0
        put_loss = np.sum(np.clip(puts[:, 0] - k, 0, None) * puts[:, 1]) if len(puts) else 0
        pain = call_loss + put_loss
        if pain < best_pain:
            best_pain, best_k = pain, float(k)
    return best_k


def net_gex(enriched: pd.DataFrame, spot: float, contract_size: float = 1.0) -> float:
    """Net dealer gamma exposure. Calls add, puts subtract (plan convention)."""
    sign = np.where(enriched["opt_type"] == "CE", 1.0, -1.0)
    leg = enriched["gamma"].to_numpy() * enriched["oi"].to_numpy() * contract_size * spot ** 2 * 0.01
    return float(np.sum(sign * leg))


def atm_iv(enriched: pd.DataFrame, spot: float) -> float:
    """Average CE/PE IV at the strike nearest spot."""
    strikes = enriched["strike"].to_numpy()
    if len(strikes) == 0:
        return float("nan")
    atm = strikes[np.argmin(np.abs(strikes - spot))]
    at = enriched[enriched["strike"] == atm]
    ivs = at.loc[at["iv"] > 0, "iv"]
    return float(ivs.mean()) if len(ivs) else float("nan")


def skew(enriched: pd.DataFrame, spot: float, moneyness: float = 0.05) -> float:
    """OTM put IV minus OTM call IV (risk-reversal proxy) at ~`moneyness` away."""
    puts = enriched[(enriched["opt_type"] == "PE") & (enriched["iv"] > 0)]
    calls = enriched[(enriched["opt_type"] == "CE") & (enriched["iv"] > 0)]
    if puts.empty or calls.empty:
        return float("nan")
    pk = spot * (1 - moneyness)
    ck = spot * (1 + moneyness)
    put_iv = puts.iloc[(puts["strike"] - pk).abs().argmin()]["iv"]
    call_iv = calls.iloc[(calls["strike"] - ck).abs().argmin()]["iv"]
    return float(put_iv - call_iv)


def chain_features(chain: pd.DataFrame, spot: float, t: float, r: float = 0.065) -> dict:
    """All chain features for one snapshot, as a flat dict (engine-friendly)."""
    enriched = enrich_chain(chain, spot, t, r)
    return {
        "pcr_oi": pcr_oi(chain),
        "pcr_volume": pcr_volume(chain),
        "max_pain": max_pain(chain),
        "atm_iv": atm_iv(enriched, spot),
        "net_gex": net_gex(enriched, spot),
        "skew": skew(enriched, spot),
    }
