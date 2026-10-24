from datetime import datetime, date, time, timedelta, timezone
from typing import Optional, Dict, Any

try:
    import zoneinfo
    IST = zoneinfo.ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))

# Official Indian Stock Exchange (NSE / BSE) Trading Holidays
INDIAN_MARKET_HOLIDAYS = {
    # 2024
    date(2024, 1, 22): "Special Ram Mandir Holiday",
    date(2024, 1, 26): "Republic Day",
    date(2024, 3, 8): "Mahashivratri",
    date(2024, 3, 25): "Holi",
    date(2024, 3, 29): "Good Friday",
    date(2024, 4, 11): "Id-Ul-Fitr",
    date(2024, 4, 17): "Ram Navami",
    date(2024, 5, 1): "Maharashtra Day",
    date(2024, 5, 20): "General Parliamentary Election",
    date(2024, 6, 17): "Bakri Id",
    date(2024, 7, 17): "Muharram",
    date(2024, 8, 15): "Independence Day",
    date(2024, 10, 2): "Mahatma Gandhi Jayanti",
    date(2024, 11, 1): "Diwali Laxmi Pujan",
    date(2024, 11, 15): "Gurunanak Jayanti",
    date(2024, 11, 20): "Maharashtra Assembly Election",
    date(2024, 12, 25): "Christmas",
    # 2025
    date(2025, 1, 26): "Republic Day",
    date(2025, 2, 26): "Mahashivratri",
    date(2025, 3, 14): "Holi",
    date(2025, 3, 31): "Id-Ul-Fitr",
    date(2025, 4, 10): "Mahavir Jayanti",
    date(2025, 4, 14): "Dr. Ambedkar Jayanti",
    date(2025, 4, 18): "Good Friday",
    date(2025, 5, 1): "Maharashtra Day",
    date(2025, 6, 7): "Bakri Id",
    date(2025, 8, 15): "Independence Day",
    date(2025, 8, 27): "Ganesh Chaturthi",
    date(2025, 10, 2): "Mahatma Gandhi Jayanti",
    date(2025, 10, 21): "Dussehra",
    date(2025, 10, 22): "Diwali Balipratipada",
    date(2025, 11, 5): "Gurunanak Jayanti",
    date(2025, 12, 25): "Christmas",
    # 2026
    date(2026, 1, 26): "Republic Day",
    date(2026, 3, 3): "Holi",
    date(2026, 3, 20): "Id-Ul-Fitr",
    date(2026, 4, 3): "Good Friday",
    date(2026, 4, 14): "Dr. Ambedkar Jayanti",
    date(2026, 5, 1): "Maharashtra Day",
    date(2026, 5, 27): "Bakri Id",
    date(2026, 6, 26): "Muharram",
    date(2026, 8, 15): "Independence Day",
    date(2026, 10, 2): "Mahatma Gandhi Jayanti",
    date(2026, 10, 20): "Dussehra",
    date(2026, 11, 8): "Diwali Laxmi Pujan",
    date(2026, 11, 10): "Diwali Balipratipada",
    date(2026, 11, 24): "Gurunanak Jayanti",
    date(2026, 12, 25): "Christmas",
    # 2027
    date(2027, 1, 26): "Republic Day",
    date(2027, 3, 10): "Id-Ul-Fitr",
    date(2027, 3, 22): "Holi",
    date(2027, 3, 26): "Good Friday",
    date(2027, 4, 14): "Dr. Ambedkar Jayanti",
    date(2027, 5, 1): "Maharashtra Day",
    date(2027, 8, 15): "Independence Day",
    date(2027, 10, 2): "Mahatma Gandhi Jayanti",
    date(2027, 10, 11): "Dussehra",
    date(2027, 10, 29): "Diwali Laxmi Pujan",
    date(2027, 11, 14): "Gurunanak Jayanti",
    date(2027, 12, 25): "Christmas",
}

MARKET_OPEN_TIME = time(9, 15, 0)
MARKET_CLOSE_TIME = time(15, 30, 0)


def now_ist() -> datetime:
    """Return current datetime in Indian Standard Time (IST)."""
    return datetime.now(IST)


def is_weekend(d: date) -> bool:
    """Return True if date is Saturday (5) or Sunday (6)."""
    return d.weekday() >= 5


def is_holiday(d: date) -> bool:
    """Return True if date is an official Indian exchange holiday."""
    return d in INDIAN_MARKET_HOLIDAYS


def is_trading_day(d: date) -> bool:
    """Return True if date is an Indian exchange trading day (Mon-Fri and not holiday)."""
    return not is_weekend(d) and not is_holiday(d)


def get_previous_trading_day(d: date) -> date:
    """Return the strictly preceding trading day before date d."""
    cur = d - timedelta(days=1)
    while not is_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def get_next_trading_day(d: date) -> date:
    """Return the strictly succeeding trading day after date d."""
    cur = d + timedelta(days=1)
    while not is_trading_day(cur):
        cur += timedelta(days=1)
    return cur


def get_latest_completed_trading_day(as_of: Optional[datetime] = None) -> date:
    """
    Return the date of the latest COMPLETED trading session.
    If today is a trading day and time is >= 15:30: today's session is completed.
    Otherwise, rolls backward to the most recent completed trading session date.
    """
    dt = as_of.astimezone(IST) if as_of else now_ist()
    today = dt.date()
    t = dt.time()

    if is_trading_day(today) and t >= MARKET_CLOSE_TIME:
        return today
    return get_previous_trading_day(today)


def is_market_open(as_of: Optional[datetime] = None) -> bool:
    """Return True if the Indian market is currently in normal trading session (09:15 to 15:30 IST)."""
    dt = as_of.astimezone(IST) if as_of else now_ist()
    today = dt.date()
    t = dt.time()

    if not is_trading_day(today):
        return False
    return MARKET_OPEN_TIME <= t < MARKET_CLOSE_TIME


def get_market_status(as_of: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Compute complete Indian stock market status including live vs last close price indicator,
    latest completed trading session, and next opening timestamp.
    """
    dt = as_of.astimezone(IST) if as_of else now_ist()
    today = dt.date()
    t = dt.time()

    if is_weekend(today):
        status = "CLOSED"
        reason = "WEEKEND"
        price_type = "LAST_CLOSE"
    elif is_holiday(today):
        status = "CLOSED"
        reason = "TRADING_HOLIDAY"
        price_type = "LAST_CLOSE"
    elif t < MARKET_OPEN_TIME:
        status = "CLOSED"
        reason = "PRE_MARKET"
        price_type = "LAST_CLOSE"
    elif t >= MARKET_CLOSE_TIME:
        status = "CLOSED"
        reason = "AFTER_HOURS"
        price_type = "LAST_CLOSE"
    else:
        status = "OPEN"
        reason = "REGULAR_TRADING"
        price_type = "LIVE"

    latest_completed = get_latest_completed_trading_day(dt)
    prev_session = get_previous_trading_day(latest_completed)

    # Next trading opening time
    if status == "OPEN":
        next_open = None
    elif is_trading_day(today) and t < MARKET_OPEN_TIME:
        next_open = datetime.combine(today, MARKET_OPEN_TIME, tzinfo=IST)
    else:
        next_day = get_next_trading_day(today)
        next_open = datetime.combine(next_day, MARKET_OPEN_TIME, tzinfo=IST)

    return {
        "marketStatus": status,
        "priceType": price_type,
        "reason": reason,
        "currentTime": dt.isoformat(),
        "isTradingDay": is_trading_day(today),
        "holidayName": INDIAN_MARKET_HOLIDAYS.get(today),
        "lastTradingSessionDate": latest_completed.isoformat(),
        "previousTradingSessionDate": prev_session.isoformat(),
        "nextTradingSessionTime": next_open.isoformat() if next_open else None,
        "tradingHours": {
            "open": "09:15:00",
            "close": "15:30:00",
            "timezone": "Asia/Kolkata",
            "exchange": "NSE/BSE"
        }
    }
