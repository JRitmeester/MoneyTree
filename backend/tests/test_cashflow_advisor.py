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
        # Salary on the 22nd (monthly), last seen 2026-07-22 -> next payday
        # 2026-08-22 (a Saturday, but advisor timing uses the raw expected
        # day, not the calendar-display weekend shift).
        _confirmed(
            db, name="Salary", expected_amount=3000, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 7, 22), is_income=True,
        )
        # Bills cluster, days 25 and 29 of the month right after payday:
        # both fall inside [2026-08-22, 2026-09-22).
        _confirmed(
            db, name="Energy", expected_amount=-300, cadence="monthly",
            expected_day=25, anchor_date=date(2026, 7, 25),
        )
        _confirmed(
            db, name="Water", expected_amount=-300, cadence="monthly",
            expected_day=29, anchor_date=date(2026, 7, 29),
        )
        # Rent cluster, days 1 and 6 of the following month: also inside
        # the [2026-08-22, 2026-09-22) window.
        _confirmed(
            db, name="Rent", expected_amount=-900, cadence="monthly",
            expected_day=1, anchor_date=date(2026, 7, 1),
        )
        _confirmed(
            db, name="Ground rent", expected_amount=-333, cadence="monthly",
            expected_day=6, anchor_date=date(2026, 7, 6),
        )
        # Small four-weekly item, folded into the buffer rather than given
        # its own return transfer.
        _confirmed(
            db, name="Streaming", expected_amount=-25, cadence="four_weekly",
            expected_day=None, anchor_date=date(2026, 7, 28),
        )
        # Pre-payday debit on the 20th, 2 days before the salary on the
        # 22nd: lands just before this payday, in the previous cycle.
        _confirmed(
            db, name="Credit card", expected_amount=-150, cadence="monthly",
            expected_day=20, anchor_date=date(2026, 7, 20),
        )

        advice = compute_advice(db, buffer_pct=10.0)

        assert advice.salary_confirmed is True
        assert advice.payday == date(2026, 8, 22)
        assert advice.next_payday == date(2026, 9, 22)

        # Sweep covers all debits due before next payday, plus the buffer:
        # 300 + 300 + 900 + 333 + 25 + 150 = 2008; *1.1 = 2208.8
        assert advice.sweep_amount == 2208.8

        # At most two return transfers: bills cluster and rent cluster.
        assert len(advice.return_transfers) == 2
        for transfer in advice.return_transfers:
            assert transfer.date.weekday() < 5

        bills_transfer = next(t for t in advice.return_transfers if "Energy" in t.covers)
        assert bills_transfer.amount == 600.0
        # Earliest debit covered is 2026-08-25 (Tuesday); 2 business days
        # before is 2026-08-21 (Friday).
        assert bills_transfer.date == date(2026, 8, 21)

        rent_transfer = next(t for t in advice.return_transfers if "Rent" in t.covers)
        assert rent_transfer.amount == 1233.0
        # Earliest debit covered is 2026-09-01 (Tuesday); 2 business days
        # before is 2026-08-28 (Friday).
        assert rent_transfer.date == date(2026, 8, 28)

        # No dedicated transfer for the small four-weekly item; it's folded.
        assert not any("Streaming" in t.covers for t in advice.return_transfers)

        # Pre-payday debit warning fires for the Credit card on the 20th.
        assert any("Credit card" in w and "before payday" in w for w in advice.warnings)

    def test_yearly_item_due_soon_warns(self, db: Session):
        _confirmed(
            db, name="Salary", expected_amount=3000, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 7, 22), is_income=True,
        )
        today = date(2026, 8, 1)
        _confirmed(
            db, name="Car insurance", expected_amount=-400, cadence="yearly",
            expected_day=15, anchor_date=date(2025, 8, 15),
        )
        advice = compute_advice(db, buffer_pct=10.0, today=today)
        assert any("Car insurance" in w and "yearly" in w for w in advice.warnings)
