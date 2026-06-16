import datetime as dt

import pytest

from dataplatform.marketcalendar import (
    ExpiryResolver, TradingCalendar, last_weekday_of_month,
    weekdays_in_range, MON, TUE, THU, FRI,
)
from dataplatform.marketcalendar.expiry import ExpiryRule


def test_last_weekday_known_dates():
    # Jan 1 2021 was a Friday -> Fridays 1,8,15,22,29 -> last = 29
    assert last_weekday_of_month(2021, 1, FRI) == dt.date(2021, 1, 29)
    # Last Thursday of Jan 2021 -> 28
    assert last_weekday_of_month(2021, 1, THU) == dt.date(2021, 1, 28)


def test_last_weekday_properties():
    for (y, m) in [(2020, 2), (2024, 2), (2026, 6), (2019, 12)]:
        d = last_weekday_of_month(y, m, THU)
        assert d.month == m and d.weekday() == THU
        assert (d + dt.timedelta(days=7)).month != m  # truly the last one


def test_weekdays_in_range_count():
    days = weekdays_in_range(dt.date(2026, 6, 1), dt.date(2026, 6, 30), THU)
    assert all(x.weekday() == THU for x in days)
    assert days == sorted(days)


def test_holiday_rollback():
    cal = TradingCalendar(exchange="NSE", holidays=set())
    # make a Thursday a holiday -> expiry rolls back to Wednesday (a trading day)
    thu = dt.date(2026, 6, 25)
    assert thu.weekday() == THU
    cal.add_holidays([thu])
    rolled = cal.roll_to_trading_day(thu)
    assert rolled < thu and cal.is_trading_day(rolled)


def test_finnifty_weekly_discontinued():
    er = ExpiryResolver()
    # weekly era
    assert er.has_weekly("FINNIFTY", dt.date(2023, 6, 1)) is True
    assert er.next_weekly_expiry("FINNIFTY", dt.date(2023, 6, 1)) is not None
    # post-discontinuation: monthly-only
    assert er.has_weekly("FINNIFTY", dt.date(2025, 6, 1)) is False
    assert er.next_weekly_expiry("FINNIFTY", dt.date(2025, 6, 1)) is None


def test_nifty_weekly_era_boundary():
    er = ExpiryResolver()
    assert er.has_weekly("NIFTY", dt.date(2018, 1, 1)) is False   # pre-weekly
    assert er.has_weekly("NIFTY", dt.date(2022, 1, 1)) is True


def test_current_expiry_weekdays():
    er = ExpiryResolver()
    # As of June 2026: NSE (Nifty) expires TUESDAY, BSE (Sensex) THURSDAY
    assert er.next_weekly_expiry("NIFTY", dt.date(2026, 6, 1)).weekday() == TUE
    assert er.next_weekly_expiry("SENSEX", dt.date(2026, 6, 1)).weekday() == THU
    # historical: Nifty weekly was THURSDAY before the 2025-09 swap
    assert er.next_weekly_expiry("NIFTY", dt.date(2022, 6, 1)).weekday() == THU


def test_current_monthly_after_asof():
    er = ExpiryResolver()
    asof = dt.date(2026, 6, 10)
    exp = er.current_monthly_expiry("NIFTY", asof)
    assert exp >= asof


def test_expiries_in_range_has_monthly():
    er = ExpiryResolver()
    rows = er.expiries_in_range("NIFTY", dt.date(2026, 6, 1), dt.date(2026, 8, 31))
    dates = [r["date"] for r in rows]
    assert dates == sorted(dates)
    assert any(r["type"] == "monthly" for r in rows)


def test_no_rule_raises():
    er = ExpiryResolver(rules=[ExpiryRule("NIFTY", dt.date(2020, 1, 1), None,
                                          False, None, THU)])
    with pytest.raises(ValueError):
        er.rule_on("SENSEX", dt.date(2026, 1, 1))


def test_finnifty_monthly_tuesday_after_weekly_drop():
    # Verified: FinNifty monthly = last TUESDAY both right after the 2024-11
    # weekly drop and after the 2025-09 NSE swap (it never moved off Tuesday).
    er = ExpiryResolver()
    assert er.rule_on("FINNIFTY", dt.date(2025, 6, 1)).monthly_weekday == TUE
    assert er.rule_on("FINNIFTY", dt.date(2026, 6, 1)).monthly_weekday == TUE


def test_sensex_expiry_weekday_history():
    # Verified BSE history: pre-2023 monthly Thu -> 2023-05 relaunch weekly Fri
    # -> 2025-01 weekly Tue -> 2025-09 weekly Thu.
    er = ExpiryResolver()
    assert er.rule_on("SENSEX", dt.date(2022, 6, 1)).monthly_weekday == THU
    assert er.rule_on("SENSEX", dt.date(2023, 6, 1)).weekly_weekday == FRI
    assert er.rule_on("SENSEX", dt.date(2025, 3, 1)).weekly_weekday == TUE
    assert er.rule_on("SENSEX", dt.date(2026, 6, 1)).weekly_weekday == THU
