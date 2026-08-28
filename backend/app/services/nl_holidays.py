"""Dutch public holidays, used to shift recurring-payment expected dates
onto the nearest actual banking day (see spec "Recurring-payment
detection", income/expense shift rule).

Fixed-date holidays: New Year's Day, King's Day, Liberation Day (only in
years divisible by 5, when it's a full public holiday), and both days of
Christmas. Easter-derived holidays (Good Friday, Easter Monday, Ascension
Day, Whit Monday) are computed from the anonymous Gregorian Easter
algorithm (Meeus/Jones/Butcher).
"""
from __future__ import annotations

from datetime import date, timedelta


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday for `year`, via the anonymous
    Meeus/Jones/Butcher algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _fixed_holidays(year: int) -> set[date]:
    holidays = {
        date(year, 1, 1),  # New Year's Day
        date(year, 4, 27),  # King's Day
        date(year, 12, 25),  # Christmas Day
        date(year, 12, 26),  # Boxing Day
    }
    if year % 5 == 0:
        holidays.add(date(year, 5, 5))  # Liberation Day (lustrum years)
    return holidays


def _easter_holidays(year: int) -> set[date]:
    easter = easter_sunday(year)
    return {
        easter - timedelta(days=2),  # Good Friday
        easter + timedelta(days=1),  # Easter Monday
        easter + timedelta(days=39),  # Ascension Day
        easter + timedelta(days=50),  # Whit Monday
    }


def is_nl_holiday(d: date) -> bool:
    return d in _fixed_holidays(d.year) or d in _easter_holidays(d.year)


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and not is_nl_holiday(d)


def shift_forward_to_business_day(d: date) -> date:
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def shift_backward_to_business_day(d: date) -> date:
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d
