"""Tests for the cash-flow calendar projection and transfer advisor.

See docs/superpowers/specs/2026-08-27-financial-insights-design.md, section
"Cash-flow calendar and transfer advisor", and
.superpowers/sdd/2026-08-28-recurring-cashflow/task-5-brief.md.
"""
from datetime import date

from sqlalchemy.orm import Session

from app.models import RecurringPayment, RecurringPaymentOccurrence

from .conftest import make_transaction
from app.services.cashflow_advisor import (
    business_days_before,
    compute_advice,
    next_business_day,
    project_calendar_month,
)


def _confirmed(
    db: Session,
    *,
    name: str,
    expected_amount: float,
    cadence: str,
    expected_day: int | None,
    anchor_date: date,
    is_income: bool = False,
) -> RecurringPayment:
    payment = RecurringPayment(
        merchant_pattern=name,
        name=name,
        expected_amount=expected_amount,
        cadence=cadence,
        expected_day=expected_day,
        anchor_date=anchor_date,
        status="confirmed",
        is_income=is_income,
    )
    db.add(payment)
    db.flush()
    if is_income:
        # `_find_salary_payment` identifies salary by occurrence count, so
        # income fixtures need at least one occurrence to be recognized.
        tx = make_transaction(db, bedrag=expected_amount, datum=anchor_date, naam=name)
        db.add(
            RecurringPaymentOccurrence(
                recurring_payment_id=payment.id,
                transaction_id=tx.id,
                amount=expected_amount,
                date=anchor_date,
            )
        )
    db.commit()
    db.refresh(payment)
    return payment


class TestBusinessDayHelpers:
    def test_next_business_day_keeps_weekday(self):
        # 2026-08-24 is a Monday.
        d = date(2026, 8, 24)
        assert next_business_day(d) == d

    def test_next_business_day_shifts_saturday_forward(self):
        # 2026-08-22 is a Saturday.
        assert next_business_day(date(2026, 8, 22)) == date(2026, 8, 24)

    def test_business_days_before_skips_weekend(self):
        # 2026-08-24 is a Monday; 2 business days before skips the weekend.
        assert business_days_before(date(2026, 8, 24), 2) == date(2026, 8, 20)


class TestCalendarProjection:
    def test_monthly_item_shifted_off_weekend(self, db: Session):
        payment = _confirmed(
            db, name="Rent", expected_amount=-900, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 7, 22),
        )
        items = project_calendar_month([payment], 2026, 8, salary_payment_id=None)
        assert len(items) == 1
        # 2026-08-22 is a Saturday, shifts to Monday 2026-08-24.
        assert items[0].date == date(2026, 8, 24)
        assert items[0].amount == -900

    def test_four_weekly_item_steps_from_anchor(self, db: Session):
        payment = _confirmed(
            db, name="Subscription", expected_amount=-25, cadence="four_weekly",
            expected_day=None, anchor_date=date(2026, 7, 28),
        )
        items = project_calendar_month([payment], 2026, 8, salary_payment_id=None)
        dates = [i.date for i in items]
        assert date(2026, 8, 25) in dates

    def test_yearly_item_only_in_its_month(self, db: Session):
        payment = _confirmed(
            db, name="Insurance", expected_amount=-120, cadence="yearly",
            expected_day=15, anchor_date=date(2025, 3, 15),
        )
        assert project_calendar_month([payment], 2026, 8, salary_payment_id=None) == []
        march_items = project_calendar_month([payment], 2026, 3, salary_payment_id=None)
        assert len(march_items) == 1

    def test_salary_flag_set_for_matching_payment(self, db: Session):
        salary = _confirmed(
            db, name="Salary", expected_amount=3000, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 7, 22), is_income=True,
        )
        items = project_calendar_month([salary], 2026, 8, salary_payment_id=salary.id)
        assert items[0].is_salary is True


class TestAdvisor:
    def test_no_confirmed_salary_returns_explicit_state(self, db: Session):
        advice = compute_advice(db, buffer_pct=10.0)
        assert advice.salary_confirmed is False
        assert advice.message == "Confirm your salary as recurring income first"
        assert advice.sweep_amount is None
        assert advice.return_transfers == []

    def test_real_pattern_sweep_transfers_and_warnings(self, db: Session):
        # Salary on the 22nd (monthly), last seen 2026-07-22 -> raw next
        # payday 2026-08-22 (a Saturday). Income shifts backward, so it's
        # paid early on Friday 2026-08-21; raw next-next payday 2026-09-22
        # is already a weekday.
        _confirmed(
            db, name="Salary", expected_amount=3000, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 7, 22), is_income=True,
        )
        # Bills cluster, days 25 and 29 of the month right after payday.
        # 2026-08-29 is a Saturday, shifted to Monday 2026-08-31.
        _confirmed(
            db, name="Energy", expected_amount=-300, cadence="monthly",
            expected_day=25, anchor_date=date(2026, 7, 25),
        )
        _confirmed(
            db, name="Water", expected_amount=-300, cadence="monthly",
            expected_day=29, anchor_date=date(2026, 7, 29),
        )
        # Rent cluster, days 1 and 6 of the following month (2026-09-06 is
        # a Sunday, shifted to Monday 2026-09-07).
        _confirmed(
            db, name="Rent", expected_amount=-900, cadence="monthly",
            expected_day=1, anchor_date=date(2026, 7, 1),
        )
        _confirmed(
            db, name="Ground rent", expected_amount=-333, cadence="monthly",
            expected_day=6, anchor_date=date(2026, 7, 6),
        )
        # Small four-weekly item, folded into the standing buffer rather
        # than given its own return transfer.
        _confirmed(
            db, name="Streaming", expected_amount=-25, cadence="four_weekly",
            expected_day=None, anchor_date=date(2026, 7, 28),
        )
        # Pre-payday debit on the 20th: lands just before this payday, in
        # the previous cycle, but also recurs on 2026-09-20 (shifted to
        # 2026-09-21) inside this cycle's sweep window.
        _confirmed(
            db, name="Credit card", expected_amount=-150, cadence="monthly",
            expected_day=20, anchor_date=date(2026, 7, 20),
        )

        # today is before the raw 2026-08-22 payday, so it doesn't trigger
        # the stale-payday rollover (covered by its own test below).
        advice = compute_advice(db, buffer_pct=10.0, today=date(2026, 8, 20))

        assert advice.salary_confirmed is True
        assert advice.payday == date(2026, 8, 21)
        assert advice.next_payday == date(2026, 9, 22)

        # All debits before next payday: 300 + 300 + 900 + 333 + 25 + 150 =
        # 2008. Being paid a day earlier (2026-08-21) than a plain
        # weekend-only shift gives both bill clusters just enough lead
        # time to be swept via return transfer instead of kept in
        # checking: sweep_amount = 2008 * 1.1 = 2208.8.
        assert advice.keep_in_checking == 0.0
        assert advice.sweep_amount == 2208.8
        assert advice.standing_buffer == 25.0

        # Both non-four-weekly clusters get a transfer now that payday
        # lands a day earlier.
        assert len(advice.return_transfers) == 2
        by_covers = {frozenset(t.covers): t for t in advice.return_transfers}
        energy_water = by_covers[frozenset({"Energy", "Water"})]
        rent = by_covers[frozenset({"Rent", "Ground rent"})]

        assert energy_water.amount == 600.0
        # Earliest debit covered is 2026-08-25 (Tuesday); 2 business days
        # before is 2026-08-21, which is exactly payday.
        assert energy_water.date == date(2026, 8, 21)
        assert energy_water.date >= advice.payday

        assert rent.amount == 1233.0
        # Earliest debit covered is 2026-09-01 (Tuesday); 2 business days
        # before is 2026-08-28 (Friday), which is on/after payday.
        assert rent.date == date(2026, 8, 28)
        assert rent.date.weekday() < 5
        assert rent.date >= advice.payday

        # No dedicated transfer for the small four-weekly item; it's folded
        # into the standing buffer instead.
        assert not any("Streaming" in t.covers for t in advice.return_transfers)

        # Pre-payday debit fires for the Credit card on the 20th, as
        # structured data (rendered as a table in the UI).
        credit_card = next(d for d in advice.pre_payday_debits if d.name == "Credit card")
        assert credit_card.date == date(2026, 8, 20)
        assert credit_card.days_before == 1

    def test_return_transfer_never_precedes_payday(self, db: Session):
        """Critical fix: a debit landing within ~2 business days after
        payday can't be pre-funded by a return transfer (the transfer would
        have to be sent before the money is even swept), so it's kept in
        checking instead of scheduled with an impossible date."""
        _confirmed(
            db, name="Salary", expected_amount=3000, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 7, 22), is_income=True,
        )
        # Income shifts Sat 2026-08-22 backward to Fri 2026-08-21; this
        # debit lands 2026-08-24, leaving no room for a 2-business-day
        # transfer (2 business days before 2026-08-24 is 2026-08-20, which
        # precedes payday).
        _confirmed(
            db, name="Gym", expected_amount=-40, cadence="monthly",
            expected_day=24, anchor_date=date(2026, 7, 24),
        )
        advice = compute_advice(db, buffer_pct=0.0, today=date(2026, 8, 20))

        assert advice.return_transfers == []
        assert advice.keep_in_checking == 40.0
        # Sweep total excludes the kept-in-checking amount (buffer is 0%).
        assert advice.sweep_amount == 0.0
        for transfer in advice.return_transfers:
            assert transfer.date >= advice.payday

    def test_four_weekly_fold_threshold_both_sides(self, db: Session):
        _confirmed(
            db, name="Salary", expected_amount=3000, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 7, 22), is_income=True,
        )
        # Below/at threshold: folded into the standing buffer, no dedicated
        # transfer.
        _confirmed(
            db, name="Streaming", expected_amount=-25, cadence="four_weekly",
            expected_day=None, anchor_date=date(2026, 7, 28),
        )
        # Above threshold: 2026-07-29 + 28 days = 2026-08-26 (Wednesday),
        # well clear of payday (2026-08-24) for the 2-business-day rule.
        _confirmed(
            db, name="Big subscription", expected_amount=-80, cadence="four_weekly",
            expected_day=None, anchor_date=date(2026, 7, 29),
        )

        advice = compute_advice(db, buffer_pct=0.0, today=date(2026, 8, 20))

        assert advice.standing_buffer == 25.0
        assert len(advice.return_transfers) == 1
        transfer = advice.return_transfers[0]
        assert transfer.cadence == "four_weekly"
        assert transfer.covers == ["Big subscription"]
        assert transfer.amount == 80.0
        assert transfer.date == date(2026, 8, 24)

    def test_payday_matches_calendar_shifted_salary_date(self, db: Session):
        """Saturday-expected salary is paid early on Friday in both the
        calendar and the advisor (income shifts backward)."""
        salary = _confirmed(
            db, name="Salary", expected_amount=3000, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 7, 22), is_income=True,
        )
        advice = compute_advice(db, buffer_pct=10.0, today=date(2026, 8, 20))
        assert advice.payday == date(2026, 8, 21)

        calendar_items = project_calendar_month([salary], 2026, 8, salary_payment_id=salary.id)
        salary_item = next(i for i in calendar_items if i.is_salary)
        assert salary_item.date == date(2026, 8, 21) == advice.payday

    def test_stale_payday_rolls_forward_with_warning(self, db: Session):
        """A salary whose next-expected date has already passed (the
        detector hasn't matched a new occurrence yet) rolls forward by
        cadence until it's not in the past, and warns about it."""
        _confirmed(
            db, name="Salary", expected_amount=3000, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 6, 22), is_income=True,
        )
        # Raw next-expected from anchor 2026-06-22 is 2026-07-22, long past
        # "today" of 2026-08-25; rolls forward through 2026-08-22 to
        # 2026-09-22 (already a weekday, no shift needed).
        advice = compute_advice(db, buffer_pct=10.0, today=date(2026, 8, 25))

        assert advice.payday == date(2026, 9, 22)
        assert any(
            "2026-07-22" in w and "has not been seen yet" in w for w in advice.warnings
        )

    def test_overflow_cluster_beyond_cap_still_fully_covered_by_sweep(self, db: Session):
        """A third cluster beyond MAX_RETURN_TRANSFERS doesn't get its own
        transfer, but its amount is never dropped from the sweep."""
        _confirmed(
            db, name="Salary", expected_amount=3000, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 7, 22), is_income=True,
        )
        _confirmed(
            db, name="Big bill", expected_amount=-500, cadence="monthly",
            expected_day=1, anchor_date=date(2026, 7, 1),
        )
        _confirmed(
            db, name="Medium bill", expected_amount=-400, cadence="monthly",
            expected_day=10, anchor_date=date(2026, 7, 10),
        )
        _confirmed(
            db, name="Small bill", expected_amount=-100, cadence="monthly",
            expected_day=20, anchor_date=date(2026, 7, 20),
        )

        advice = compute_advice(db, buffer_pct=10.0, today=date(2026, 8, 20))

        assert len(advice.return_transfers) == 2
        covered = {name for t in advice.return_transfers for name in t.covers}
        assert covered == {"Big bill", "Medium bill"}
        assert advice.keep_in_checking == 0.0
        # The overflow "Small bill" cluster is still fully counted in the
        # sweep: no money is silently lost by not getting a transfer.
        assert advice.sweep_amount == round((500 + 400 + 100) * 1.1, 2)

    def test_breakdown_items_and_totals_add_up(self, db: Session):
        """The advice exposes the full calculation: every debit in the
        window as a line item, which ones are kept in checking, the covered
        total, and the buffer amount, such that
        covered_total + buffer_amount == sweep_amount."""
        _confirmed(
            db, name="Salary", expected_amount=3000, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 7, 22), is_income=True,
        )
        _confirmed(
            db, name="Rent", expected_amount=-900, cadence="monthly",
            expected_day=1, anchor_date=date(2026, 7, 1),
        )
        # Lands 2026-08-24, too close after payday (2026-08-21) for the
        # 2-business-day rule: kept in checking, excluded from the sweep.
        _confirmed(
            db, name="Gym", expected_amount=-40, cadence="monthly",
            expected_day=24, anchor_date=date(2026, 7, 24),
        )

        advice = compute_advice(db, buffer_pct=10.0, today=date(2026, 8, 20))

        items = {i.name: i for i in advice.sweep_items}
        assert set(items) == {"Rent", "Gym"}
        assert items["Rent"].kept_in_checking is False
        assert items["Rent"].amount == 900.0
        assert items["Rent"].date == date(2026, 9, 1)
        assert items["Gym"].kept_in_checking is True

        assert advice.keep_in_checking == 40.0
        assert advice.covered_total == 900.0
        assert advice.buffer_amount == 90.0
        assert advice.sweep_amount == 990.0
        assert advice.covered_total + advice.buffer_amount == advice.sweep_amount

    def test_breakdown_empty_without_salary(self, db: Session):
        advice = compute_advice(db, buffer_pct=10.0)
        assert advice.sweep_items == []
        assert advice.covered_total == 0.0
        assert advice.buffer_amount == 0.0

    def test_anchored_advice_uses_anchor_window(self, db: Session):
        """With anchor_payday, the sweep window starts at the anchor (a past
        date is fine) and the stale-payday roll-forward is skipped."""
        _confirmed(
            db, name="Salary", expected_amount=3000, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 7, 22), is_income=True,
        )
        _confirmed(
            db, name="Rent", expected_amount=-900, cadence="monthly",
            expected_day=1, anchor_date=date(2026, 7, 1),
        )

        # today is well past the anchor; forward-looking advice would roll
        # to the September payday, but the anchored window stays put.
        advice = compute_advice(
            db, buffer_pct=0.0, today=date(2026, 9, 10), anchor_payday=date(2026, 8, 21)
        )

        assert advice.payday == date(2026, 8, 21)
        assert advice.next_payday == date(2026, 9, 22)
        # Rent lands 2026-09-01, inside [2026-08-21, 2026-09-22).
        assert advice.sweep_amount == 900.0
        assert not any("has not been seen yet" in w for w in advice.warnings)

    def test_yearly_item_due_soon_warns(self, db: Session):
        _confirmed(
            db, name="Salary", expected_amount=3000, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 7, 22), is_income=True,
        )
        today = date(2026, 8, 1)
        # expected_day=15 lands on 2026-08-15, a Saturday; the warning should
        # report the weekend-shifted date (Monday 2026-08-17), not the raw
        # calendar date, since that's the date the debit will actually hit.
        _confirmed(
            db, name="Car insurance", expected_amount=-400, cadence="yearly",
            expected_day=15, anchor_date=date(2025, 8, 15),
        )
        advice = compute_advice(db, buffer_pct=10.0, today=today)
        matching = [y for y in advice.yearly_due if y.name == "Car insurance"]
        assert len(matching) == 1
        # The weekend-shifted date (Monday 2026-08-17), not the raw 15th,
        # since that is when the debit will actually hit.
        assert matching[0].date == date(2026, 8, 17)
