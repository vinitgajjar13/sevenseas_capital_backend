import unittest
from datetime import datetime, date, timezone, timedelta
from app.services.market_calendar import (
    IST,
    is_weekend,
    is_holiday,
    is_trading_day,
    is_market_open,
    get_market_status,
    get_latest_completed_trading_day,
    get_previous_trading_day,
    get_next_trading_day,
    INDIAN_MARKET_HOLIDAYS,
)

class TestMarketCalendar(unittest.TestCase):

    def test_regular_market_open(self):
        # Friday 11:30 AM IST (Normal trading session)
        dt = datetime(2026, 10, 23, 11, 30, 0, tzinfo=IST)
        self.assertTrue(is_trading_day(dt.date()))
        self.assertTrue(is_market_open(dt))

        status = get_market_status(dt)
        self.assertEqual(status["marketStatus"], "OPEN")
        self.assertEqual(status["priceType"], "LIVE")
        self.assertEqual(status["reason"], "REGULAR_TRADING")
        self.assertEqual(status["lastTradingSessionDate"], "2026-10-22") # Completed session prior to live

    def test_pre_market_hours(self):
        # Monday 08:30 AM IST (Before 09:15 open)
        dt = datetime(2026, 10, 26, 8, 30, 0, tzinfo=IST)
        self.assertTrue(is_trading_day(dt.date()))
        self.assertFalse(is_market_open(dt))

        status = get_market_status(dt)
        self.assertEqual(status["marketStatus"], "CLOSED")
        self.assertEqual(status["priceType"], "LAST_CLOSE")
        self.assertEqual(status["reason"], "PRE_MARKET")
        self.assertEqual(status["lastTradingSessionDate"], "2026-10-23") # Friday's close

    def test_after_hours_trading_day(self):
        # Friday 16:00 PM IST (After 15:30 close)
        dt = datetime(2026, 10, 23, 16, 0, 0, tzinfo=IST)
        self.assertTrue(is_trading_day(dt.date()))
        self.assertFalse(is_market_open(dt))

        status = get_market_status(dt)
        self.assertEqual(status["marketStatus"], "CLOSED")
        self.assertEqual(status["priceType"], "LAST_CLOSE")
        self.assertEqual(status["reason"], "AFTER_HOURS")
        self.assertEqual(status["lastTradingSessionDate"], "2026-10-23") # Today completed

    def test_weekend_saturday_and_sunday(self):
        # Saturday evening
        dt_sat = datetime(2026, 10, 24, 18, 25, 0, tzinfo=IST)
        self.assertTrue(is_weekend(dt_sat.date()))
        self.assertFalse(is_trading_day(dt_sat.date()))
        self.assertFalse(is_market_open(dt_sat))

        status_sat = get_market_status(dt_sat)
        self.assertEqual(status_sat["marketStatus"], "CLOSED")
        self.assertEqual(status_sat["priceType"], "LAST_CLOSE")
        self.assertEqual(status_sat["reason"], "WEEKEND")
        self.assertEqual(status_sat["lastTradingSessionDate"], "2026-10-23") # Friday
        self.assertEqual(status_sat["previousTradingSessionDate"], "2026-10-22") # Thursday

        # Sunday morning
        dt_sun = datetime(2026, 10, 25, 10, 0, 0, tzinfo=IST)
        status_sun = get_market_status(dt_sun)
        self.assertEqual(status_sun["marketStatus"], "CLOSED")
        self.assertEqual(status_sun["priceType"], "LAST_CLOSE")
        self.assertEqual(status_sun["reason"], "WEEKEND")
        self.assertEqual(status_sun["lastTradingSessionDate"], "2026-10-23") # Still Friday

    def test_indian_market_holiday(self):
        # Mahatma Gandhi Jayanti: 2026-10-02 (Friday)
        dt_holiday = datetime(2026, 10, 2, 11, 0, 0, tzinfo=IST)
        self.assertTrue(is_holiday(dt_holiday.date()))
        self.assertFalse(is_trading_day(dt_holiday.date()))
        self.assertFalse(is_market_open(dt_holiday))

        status_holiday = get_market_status(dt_holiday)
        self.assertEqual(status_holiday["marketStatus"], "CLOSED")
        self.assertEqual(status_holiday["priceType"], "LAST_CLOSE")
        self.assertEqual(status_holiday["reason"], "TRADING_HOLIDAY")
        self.assertEqual(status_holiday["holidayName"], "Mahatma Gandhi Jayanti")
        self.assertEqual(status_holiday["lastTradingSessionDate"], "2026-10-01") # Thursday before holiday

    def test_long_weekend_holiday_rollback(self):
        # Good Friday: 2026-04-03
        # Thursday 2026-04-02 was the last trading day.
        # On Saturday 2026-04-04 (weekend after Good Friday):
        dt_long_weekend = datetime(2026, 4, 4, 14, 0, 0, tzinfo=IST)
        status = get_market_status(dt_long_weekend)
        self.assertEqual(status["marketStatus"], "CLOSED")
        self.assertEqual(status["lastTradingSessionDate"], "2026-04-02") # Thursday, skipped Friday holiday

    def test_next_trading_session_calculation(self):
        # On Friday evening 2026-10-23 at 18:00
        dt = datetime(2026, 10, 23, 18, 0, 0, tzinfo=IST)
        status = get_market_status(dt)
        # Next opening is Monday 2026-10-26 at 09:15
        self.assertEqual(status["nextTradingSessionTime"], "2026-10-26T09:15:00+05:30")

if __name__ == "__main__":
    unittest.main()
