"""#24 — config fingerprint + diff for backtest/live parameter alignment."""
from backtest.provenance import config_fingerprint, diff_configs, params_match


def test_fingerprint_is_order_independent_and_stable():
    a = {"risk": {"per_trade": 1.0, "cap": 15}, "execution": {"slip": 2}, "strategy": {"x": 1}}
    b = {"strategy": {"x": 1}, "execution": {"slip": 2}, "risk": {"cap": 15, "per_trade": 1.0}}
    assert config_fingerprint(a) == config_fingerprint(b)          # key order irrelevant
    assert params_match(config_fingerprint(a), config_fingerprint(b))


def test_fingerprint_changes_when_a_relevant_value_changes():
    a = {"risk": {"per_trade": 1.0}, "execution": {}, "strategy": {}}
    b = {"risk": {"per_trade": 2.0}, "execution": {}, "strategy": {}}
    assert config_fingerprint(a) != config_fingerprint(b)


def test_fingerprint_ignores_non_result_sections():
    a = {"risk": {"r": 1}, "execution": {}, "strategy": {}, "system": {"log_level": "INFO"}}
    b = {"risk": {"r": 1}, "execution": {}, "strategy": {}, "system": {"log_level": "DEBUG"}}
    assert config_fingerprint(a) == config_fingerprint(b)          # system not fingerprinted


def test_diff_configs_reports_paths():
    a = {"risk": {"per_trade": 1.0, "cap": 15}, "execution": {}, "strategy": {}}
    b = {"risk": {"per_trade": 2.0, "cap": 15}, "execution": {}, "strategy": {}}
    d = diff_configs(a, b)
    assert d["match"] is False
    paths = [x["path"] for x in d["differences"]["risk"]]
    assert "risk.per_trade" in paths
    assert diff_configs(a, a)["match"] is True
