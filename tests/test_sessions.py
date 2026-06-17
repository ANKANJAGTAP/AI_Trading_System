"""P1#10 — venue-aware sessions: NSE closed but MCX open in the evening; all
closed on holidays/weekends. Pure (uses the seed calendar, no DB)."""
import datetime as dt

from common.market_time import IST
from common.sessions import MarketSessions, Venue, venue_for


def _at(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=IST)


def test_venue_for_mapping():
    assert venue_for("MCX") == Venue.MCX
    assert venue_for("NFO") == Venue.NFO
    assert venue_for("NSE") == Venue.NSE_EQ
    assert venue_for("BSE") == Venue.NSE_EQ
    assert venue_for(None) == Venue.NSE_EQ


def test_equity_open_midday():
    assert MarketSessions().is_open(Venue.NSE_EQ, _at(2026, 6, 17, 11, 0)) is True


def test_nse_closed_mcx_open_in_evening():
    s = MarketSessions()
    t = _at(2026, 6, 17, 18, 0)   # Wed, after equity close, MCX still open
    assert s.is_open(Venue.NSE_EQ, t) is False
    assert s.is_open(Venue.MCX, t) is True
    assert s.any_open(t) is True


def test_all_closed_on_holiday():
    # 2026-01-26 is a seed holiday (Republic Day).
    assert MarketSessions().any_open(_at(2026, 1, 26, 11, 0)) is False


def test_all_closed_on_weekend():
    # 2026-06-20 is a Saturday.
    assert MarketSessions().any_open(_at(2026, 6, 20, 11, 0)) is False
