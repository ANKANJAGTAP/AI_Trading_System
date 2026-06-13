import math

from demo.run_end_to_end import run_demo


def test_demo_runs_all_five_pillars():
    out = run_demo()

    # P1 ingest
    assert out["ingest"]["rows"] > 0 and out["ingest"]["lot_size"] > 0
    # P2 features
    assert out["features"]["observations"] > 0
    assert len(out["features"]["feature_columns"]) >= 5
    # P3 validation
    v = out["validation"]
    assert v["labelled_events"] > 0
    assert v["cpcv_paths"] == 5
    assert 0.0 <= v["cpcv_mean_accuracy"] <= 1.0
    # P4/P5 backtest
    b = out["backtest"]
    assert b["n_trades"] >= 0
    assert math.isfinite(b["net_pnl"])
    assert b["bias_audit"]["costs_modelled"] is True
