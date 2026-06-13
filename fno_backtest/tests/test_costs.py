from fno_backtest.costs import CostConfig, leg_cost, round_trip_cost


def test_sell_option_has_stt_buy_has_stamp():
    cfg = CostConfig()
    sell = leg_cost(100, 75, "SELL", "OPT", cfg)
    buy = leg_cost(100, 75, "BUY", "OPT", cfg)
    assert sell["stt"] > 0 and buy["stt"] == 0      # STT only on sell
    assert buy["stamp"] > 0 and sell["stamp"] == 0  # stamp only on buy


def test_gst_is_on_brokerage_exch_sebi():
    cfg = CostConfig()
    c = leg_cost(100, 75, "SELL", "OPT", cfg)
    assert abs(c["gst"] - cfg.gst * (c["brokerage"] + c["exch"] + c["sebi"])) < 1e-9


def test_total_is_sum_of_components():
    c = leg_cost(120, 50, "BUY", "OPT")
    parts = c["brokerage"] + c["stt"] + c["exch"] + c["sebi"] + c["stamp"] + c["gst"]
    assert abs(c["total"] - parts) < 1e-9


def test_futures_vs_options_stt_differ():
    fut = leg_cost(20000, 50, "SELL", "FUT")
    opt = leg_cost(20000, 50, "SELL", "OPT")
    assert opt["stt"] > fut["stt"]                  # option STT rate > futures


def test_round_trip_positive_and_zero_brokerage():
    assert round_trip_cost(100, 120, 75, "BUY", "OPT") > 0
    cfg = CostConfig(brokerage_per_order=0.0)
    assert leg_cost(100, 75, "SELL", "OPT", cfg)["brokerage"] == 0.0
