"""run_sweep CLI pure helpers (no DB/engine — heavy imports live inside _run)."""
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "run_sweep.py")
_spec = importlib.util.spec_from_file_location("run_sweep_cli", _PATH)
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)


def test_coerce_value_types():
    assert rs.coerce_value("20") == 20 and isinstance(rs.coerce_value("20"), int)
    assert rs.coerce_value("1.5") == 1.5
    assert rs.coerce_value("true") is True and rs.coerce_value("False") is False
    assert rs.coerce_value("15:20") == "15:20"          # non-numeric stays str
    assert rs.coerce_value(" 7 ") == 7                   # trimmed


def test_build_grid_labels_and_overrides():
    grid = rs.build_grid("strategy.intraday_stocks.regime.adx_trend_min", ["15", "20", "30"])
    assert [c["label"] for c in grid] == [
        "adx_trend_min=15", "adx_trend_min=20", "adx_trend_min=30"]
    assert grid[0]["overrides"] == {"strategy.intraday_stocks.regime.adx_trend_min": 15}
    assert grid[1]["overrides"]["strategy.intraday_stocks.regime.adx_trend_min"] == 20
    assert len(rs.build_grid("a.b.c", ["1", "", "2"])) == 2      # blanks skipped


def test_summarize_config_gross_net():
    res = {"trades": [{"pnl": 100.0, "fees": 20.0},
                      {"pnl": -60.0, "fees": 15.0},
                      {"pnl": 0.0, "fees": 5.0}],
           "metrics": {"sharpe": -0.4, "expectancy_R": -0.1}}
    s = rs.summarize_config(res)
    assert s["trades"] == 3
    assert s["net_pnl"] == 40.0                          # 100 - 60 + 0
    assert s["fees"] == 40.0                             # 20 + 15 + 5
    assert s["gross_pnl"] == 80.0                        # net + fees
    assert s["win_rate_pct"] == round(1 / 3 * 100, 1)    # one winner of three
    assert s["sharpe"] == -0.4


def test_summarize_config_empty():
    s = rs.summarize_config({"trades": [], "metrics": {}})
    assert s["trades"] == 0 and s["net_pnl"] == 0.0 and s["win_rate_pct"] == 0.0
