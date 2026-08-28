"""Tests for Dutch public holiday calculation."""
from datetime import date

from app.services.nl_holidays import (
    easter_sunday,
    is_business_day,
    is_nl_holiday,
    shift_backward_to_business_day,
    shift_forward_to_business_day,
)


class TestEasterSunday:
    def test_easter_2026(self):
        assert easter_sunday(2026) == date(2026, 4, 5)

    def test_easter_2024(self):
        assert easter_sunday(2024) == date(2024, 3, 31)

    def test_easter_2025(self):
        assert easter_sunday(2025) == date(2025, 4, 20)


class TestIsNlHoliday:
    def test_new_years_day(self):
        assert is_nl_holiday(date(2026, 1, 1)) is True

    def test_kings_day(self):
        assert is_nl_holiday(date(2026, 4, 27)) is True

    def test_christmas(self):
        assert is_nl_holiday(date(2026, 12, 25)) is True
        assert is_nl_holiday(date(2026, 12, 26)) is True

    def test_liberation_day_lustrum_year(self):
        assert is_nl_holiday(date(2025, 5, 5)) is True

    def test_liberation_day_not_lustrum_year(self):
        assert is_nl_holiday(date(2026, 5, 5)) is False

    def test_good_friday_2026(self):
        # Easter 2026-04-05 -> Good Friday 2026-04-03
        assert is_nl_holiday(date(2026, 4, 3)) is True

    def test_easter_monday_2026(self):
        assert is_nl_holiday(date(2026, 4, 6)) is True

    def test_ascension_day_2026(self):
        assert is_nl_holiday(date(2026, 4, 5) + __import__("datetime").timedelta(days=39)) is True

    def test_whit_monday_2026(self):
        assert is_nl_holiday(date(2026, 4, 5) + __import__("datetime").timedelta(days=50)) is True

    def test_ordinary_day_is_not_a_holiday(self):
        assert is_nl_holiday(date(2026, 8, 20)) is False


class TestBusinessDayShifting:
    def test_weekend_is_not_business_day(self):
        assert is_business_day(date(2026, 8, 22)) is False  # Saturday

    def test_holiday_on_weekday_is_not_business_day(self):
        assert is_business_day(date(2026, 4, 27)) is False  # King's Day, Monday

    def test_shift_forward_skips_weekend(self):
        assert shift_forward_to_business_day(date(2026, 8, 22)) == date(2026, 8, 24)

    def test_shift_backward_skips_weekend(self):
        assert shift_backward_to_business_day(date(2026, 8, 22)) == date(2026, 8, 21)

    def test_shift_backward_skips_holiday_and_weekend(self):
        # 2026-04-27 (King's Day) is a Monday; backward shift lands on
        # Friday 2026-04-24 (skipping the Sat/Sun before it as well).
        assert shift_backward_to_business_day(date(2026, 4, 27)) == date(2026, 4, 24)

    def test_shift_forward_on_business_day_is_noop(self):
        d = date(2026, 8, 24)
        assert shift_forward_to_business_day(d) == d
