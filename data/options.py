"""Options math (spec §7): Black-Scholes IV + Greeks + IV Rank/Percentile.

Implemented directly with stdlib `math` (normal CDF via erf) — no scipy/py_vollib
dependency — so the Greeks are transparent and auditable. Indian index options are
European-style; for stock options BS is the standard working approximation.

Conventions: theta is per CALENDAR DAY; vega is per 1 vol-point (1%); r is the
annual risk-free rate (decimal); t is time to expiry in years.
"""
from __future__ import annotations

import math
from datetime import date

_SQRT_2PI = math.sqrt(2 * math.pi)
DEFAULT_RISK_FREE = 0.065  # ~India 10y; operator-tunable


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _d1_d2(S: float, K: float, t: float, r: float, sigma: float):
    if sigma <= 0 or t <= 0 or S <= 0 or K <= 0:
        return None, None
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    return d1, d1 - sigma * math.sqrt(t)


def bs_price(S: float, K: float, t: float, r: float, sigma: float, opt: str = "CE") -> float:
    d1, d2 = _d1_d2(S, K, t, r, sigma)
    if d1 is None:  # degenerate -> intrinsic value
        return max(0.0, (S - K) if opt == "CE" else (K - S))
    if opt == "CE":
        return S * _norm_cdf(d1) - K * math.exp(-r * t) * _norm_cdf(d2)
    return K * math.exp(-r * t) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def greeks(S: float, K: float, t: float, r: float, sigma: float, opt: str = "CE") -> dict:
    d1, d2 = _d1_d2(S, K, t, r, sigma)
    if d1 is None:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    pdf = _norm_pdf(d1)
    sqrt_t = math.sqrt(t)
    delta = _norm_cdf(d1) if opt == "CE" else _norm_cdf(d1) - 1.0
    gamma = pdf / (S * sigma * sqrt_t)
    vega = S * pdf * sqrt_t / 100.0
    if opt == "CE":
        theta = (-(S * pdf * sigma) / (2 * sqrt_t) - r * K * math.exp(-r * t) * _norm_cdf(d2)) / 365.0
    else:
        theta = (-(S * pdf * sigma) / (2 * sqrt_t) + r * K * math.exp(-r * t) * _norm_cdf(-d2)) / 365.0
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def implied_vol(price: float, S: float, K: float, t: float, r: float, opt: str = "CE") -> float:
    """Implied volatility by bisection (robust, no derivative needed)."""
    intrinsic = max(0.0, (S - K) if opt == "CE" else (K - S))
    if price <= intrinsic or t <= 0:
        return 0.0
    lo, hi = 1e-4, 5.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        diff = bs_price(S, K, t, r, mid, opt) - price
        if abs(diff) < 1e-6:
            return mid
        if diff > 0:
            hi = mid
        else:
            lo = mid
    # Converged at the upper search bound => no real solution (illiquid/stale quote,
    # price below intrinsic). Report 0.0 (unreliable) rather than a bogus ~500% IV.
    result = 0.5 * (lo + hi)
    return 0.0 if result >= 4.99 else result


def iv_rank(current_iv: float, iv_history: list[float]) -> float:
    """IV Rank: where current IV sits in its [min,max] range over history (0-100)."""
    if not iv_history:
        return 0.0
    lo, hi = min(iv_history), max(iv_history)
    return 0.0 if hi == lo else max(0.0, min(100.0, (current_iv - lo) / (hi - lo) * 100.0))


def iv_percentile(current_iv: float, iv_history: list[float]) -> float:
    """IV Percentile: % of historical days IV was below current (0-100)."""
    if not iv_history:
        return 0.0
    return 100.0 * sum(1 for v in iv_history if v < current_iv) / len(iv_history)


def year_fraction(expiry: date, now: date | None = None) -> float:
    now = now or date.today()
    return max((expiry - now).days, 0) / 365.0


def analyze_option(
    spot: float,
    strike: float,
    expiry: date,
    premium: float,
    opt_type: str = "CE",
    r: float = DEFAULT_RISK_FREE,
    now: date | None = None,
) -> dict:
    """One-shot: IV from market premium, then Greeks at that IV."""
    t = year_fraction(expiry, now)
    iv = implied_vol(premium, spot, strike, t, r, opt_type)
    g = greeks(spot, strike, t, r, iv, opt_type)
    return {"iv": iv, "t_years": t, **g}
