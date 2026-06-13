from fno_backtest.fills import ohlc_fill, book_vwap_fill

BAR = {"open": 100, "high": 105, "low": 95, "close": 101}


def test_buy_fill_ordering():
    best = ohlc_fill("BUY", BAR, "best")
    mid = ohlc_fill("BUY", BAR, "mid")
    worst = ohlc_fill("BUY", BAR, "worst")
    assert best <= mid <= worst                 # buying worst = paying the high


def test_sell_fill_ordering():
    assert ohlc_fill("SELL", BAR, "worst") <= ohlc_fill("SELL", BAR, "best")


def test_slippage_is_adverse():
    base = ohlc_fill("BUY", BAR, "close", 0)
    slipped = ohlc_fill("BUY", BAR, "close", 50)
    assert slipped > base                       # buyer pays more with slippage
    assert ohlc_fill("SELL", BAR, "close", 50) < ohlc_fill("SELL", BAR, "close", 0)


def test_book_vwap_partial_levels():
    book = [(100.0, 10), (101.0, 10), (102.0, 100)]
    px = book_vwap_fill("BUY", book, 15)        # 10@100 + 5@101
    assert abs(px - (1000 + 505) / 15) < 1e-6


def test_book_beyond_depth_has_impact():
    book = [(100.0, 5)]
    px = book_vwap_fill("BUY", book, 10, slippage_bps=100, beyond_book_penalty=2.0)
    assert px > 100.0                           # remainder fills worse
