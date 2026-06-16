"""P9 — SEBI compliance: live orders carry the Algo-ID tag + market protection,
and the pre-live gap check enforces the prerequisites. (Pure helpers.)"""
import types

from common.compliance import (compliance_gaps, live_order_params, order_tag)


def _cfg(compliance=None, order_rps=8):
    system = types.SimpleNamespace(compliance=compliance or {})
    data = types.SimpleNamespace(rate_limits={"order": {"refill_per_sec": order_rps}})
    return types.SimpleNamespace(system=system, data=data)


def test_order_tag_truncated_to_20():
    assert len(order_tag(_cfg({"algo_id": "X" * 30}))) == 20
    assert order_tag(_cfg({})) is None


def test_live_order_params_tag_and_protection():
    c = _cfg({"algo_id": "ALGO1", "market_protection_pct": 1.0})
    assert live_order_params(c, "MARKET") == {"tag": "ALGO1", "market_protection": 1.0}
    assert live_order_params(c, "LIMIT") == {"tag": "ALGO1"}        # no protection on LIMIT
    assert "market_protection" in live_order_params(c, "SL-M")      # SL-M needs it too


def test_no_config_no_params():
    assert live_order_params(_cfg({}), "MARKET") == {}


def test_gaps_flag_missing_config():
    gaps = compliance_gaps(_cfg({}))
    assert any("algo_id" in g for g in gaps)
    assert any("static_ip" in g for g in gaps)
    assert any("market_protection" in g for g in gaps)


def test_gaps_clean_when_configured():
    c = _cfg({"algo_id": "A1", "static_ip": "1.2.3.4", "market_protection_pct": 1.0}, order_rps=8)
    assert compliance_gaps(c) == []


def test_ops_over_limit_requires_registration():
    base = {"algo_id": "A1", "static_ip": "1.2.3.4", "market_protection_pct": 1.0}
    assert any("OPS" in g for g in compliance_gaps(_cfg(base, order_rps=20)))
    assert compliance_gaps(_cfg({**base, "exchange_registered": True}, order_rps=20)) == []
