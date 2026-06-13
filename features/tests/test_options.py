import numpy as np
import pandas as pd

from features import options as opt


def test_put_call_parity():
    S, K, t, r, sig = 100, 100, 0.5, 0.06, 0.2
    call = opt.bs_price(S, K, t, r, sig, "CE")
    put = opt.bs_price(S, K, t, r, sig, "PE")
    # call - put == S - K e^{-rt}
    assert abs((call - put) - (S - K * np.exp(-r * t))) < 1e-6


def test_greek_bounds():
    S, K, t, r, sig = 100, 100, 0.5, 0.06, 0.2
    assert 0 < opt.bs_delta(S, K, t, r, sig, "CE") < 1
    assert -1 < opt.bs_delta(S, K, t, r, sig, "PE") < 0
    assert opt.bs_gamma(S, K, t, r, sig) > 0
    assert opt.bs_vega(S, K, t, r, sig) > 0


def test_implied_vol_roundtrip():
    S, K, t, r, true_sig = 100, 105, 0.25, 0.06, 0.27
    for o in ("CE", "PE"):
        price = opt.bs_price(S, K, t, r, true_sig, o)
        iv = opt.implied_vol(price, S, K, t, r, o)
        assert abs(iv - true_sig) < 1e-3


def test_implied_vol_below_intrinsic_is_zero():
    # price below intrinsic -> 0
    assert opt.implied_vol(0.0, 100, 80, 0.25, 0.06, "CE") == 0.0


def test_iv_rank_and_percentile():
    hist = pd.Series([10, 20, 30, 40, 25.0])
    assert abs(opt.iv_rank(hist) - 50.0) < 1e-9      # (25-10)/(40-10)*100
    assert abs(opt.iv_percentile(hist) - 40.0) < 1e-9  # 2 of 5 below 25


def _synthetic_chain(spot=100.0, t=30 / 365, r=0.065, sigma=0.2):
    rows = []
    for k in range(80, 125, 5):
        for o in ("CE", "PE"):
            rows.append({
                "opt_type": o, "strike": float(k),
                "close": opt.bs_price(spot, k, t, r, sigma, o),
                "oi": 1000, "volume": 500,
            })
    return pd.DataFrame(rows)


def test_chain_features():
    spot, t, r, sigma = 100.0, 30 / 365, 0.065, 0.2
    chain = _synthetic_chain(spot, t, r, sigma)
    f = opt.chain_features(chain, spot, t, r)
    assert abs(f["pcr_oi"] - 1.0) < 1e-9                 # symmetric OI
    assert abs(f["max_pain"] - spot) <= 10               # near ATM
    assert abs(f["atm_iv"] - sigma) < 0.02               # IV recovered from price
    assert abs(f["skew"]) < 0.03                          # symmetric -> ~0
    assert np.isfinite(f["net_gex"])


def test_net_gex_sign_flips_with_oi_skew():
    spot, t, r = 100.0, 30 / 365, 0.065
    chain = _synthetic_chain(spot, t, r)
    enr = opt.enrich_chain(chain, spot, t, r)
    # all-call OI -> positive net gex; all-put OI -> negative
    calls = enr.copy(); calls.loc[calls["opt_type"] == "PE", "oi"] = 0
    puts = enr.copy(); puts.loc[puts["opt_type"] == "CE", "oi"] = 0
    assert opt.net_gex(calls, spot) > 0
    assert opt.net_gex(puts, spot) < 0
