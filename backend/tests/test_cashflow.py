"""Tests for salary-anchored pay periods.

See docs/superpowers/specs/2026-08-27-financial-insights-design.md,
savings-capacity "current-month projection" note, and
.superpowers/sdd/2026-08-28-recurring-cashflow/task-4-brief.md.
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import RecurringPayment, RecurringPaymentOccurrence

from .conftest import make_transaction


def _make_confirmed_income(
    db: Session, dates: list[date], *, amount: float = 3000.0, name: str = "Salary"
) -> RecurringPayment:
    payment = RecurringPayment(
        merchant_pattern=name,
        name=name,
        expected_amount=amount,
        cadence="monthly",
        expected_day=dates[-1].day,
        anchor_date=dates[-1],
        status="confirmed",
        is_income=True,
    )
    db.add(payment)
    db.flush()
    for d in dates:
        tx = make_transaction(db, bedrag=amount, datum=d, naam=name)
        db.add(
            RecurringPaymentOccurrence(
                recurring_payment_id=payment.id, transaction_id=tx.id, amount=amount, date=d
            )
        )
    db.commit()
    return payment


class TestCashflowPeriods:
    def test_no_confirmed_salary_returns_empty(self, client, db: Session):
        resp = client.get("/api/cashflow/periods")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_dismissed_or_unconfirmed_income_ignored(self, client, db: Session):
        payment = RecurringPayment(
            merchant_pattern="Salary",
            name="Salary",
            expected_amount=3000.0,
            cadence="monthly",
            expected_day=20,
            anchor_date=date(2026, 6, 20),
            status="suggested",
            is_income=True,
        )
        db.add(payment)
        db.commit()

        resp = client.get("/api/cashflow/periods")
        assert resp.json() == []

    def test_periods_derived_from_salary_occurrences(self, client, db: Session):
        today = date.today()
        # Three monthly occurrences roughly one month apart, ending recently.
        d3 = today - timedelta(days=5)
        d2 = d3 - timedelta(days=31)
        d1 = d2 - timedelta(days=30)
        _make_confirmed_income(db, [d1, d2, d3])

        resp = client.get("/api/cashflow/periods")
        assert resp.status_code == 200
        body = resp.json()

        # Newest first: current (open) period, then two closed periods.
        assert len(body) == 3
        assert body[0]["label"] == "Current"
        assert body[0]["start_date"] == d3.isoformat()
        assert body[0]["end_date"] == today.isoformat()

        assert body[1]["start_date"] == d2.isoformat()
        assert body[1]["end_date"] == (d3 - timedelta(days=1)).isoformat()

        assert body[2]["start_date"] == d1.isoformat()
        assert body[2]["end_date"] == (d2 - timedelta(days=1)).isoformat()

    def test_count_limits_and_orders_newest_first(self, client, db: Session):
        today = date.today()
        dates = [today - timedelta(days=90 - i * 30) for i in range(4)]
        _make_confirmed_income(db, dates)

        resp = client.get("/api/cashflow/periods?count=2")
        body = resp.json()
        assert len(body) == 2
        assert body[0]["label"] == "Current"
        assert body[1]["start_date"] == dates[-2].isoformat()

    def test_picks_salary_as_income_payment_with_most_occurrences(self, client, db: Session):
        today = date.today()
        # A confirmed income payment with only 1 occurrence (e.g. a bonus)...
        _make_confirmed_income(db, [today - timedelta(days=10)], name="Bonus")
        # ...should lose to the salary with more occurrences.
        salary_dates = [today - timedelta(days=60), today - timedelta(days=30), today - timedelta(days=1)]
        _make_confirmed_income(db, salary_dates, name="Salary")

        resp = client.get("/api/cashflow/periods")
        body = resp.json()
        assert len(body) == 3
        assert body[0]["start_date"] == salary_dates[-1].isoformat()

    def test_tie_break_on_equal_occurrence_count_picks_latest_occurrence(
        self, client, db: Session
    ):
        today = date.today()
        # Two confirmed income patterns, both with 2 occurrences: the
        # tie-break must pick the one with the more recent latest occurrence,
        # not whichever was inserted (and thus assigned an id) first.
        older_latest = _make_confirmed_income(
            db, [today - timedelta(days=40), today - timedelta(days=10)], name="Older"
        )
        newer_latest = _make_confirmed_income(
            db, [today - timedelta(days=35), today - timedelta(days=5)], name="Newer"
        )
        assert older_latest.id < newer_latest.id  # inserted first, so id can't be the deciding factor

        resp = client.get("/api/cashflow/periods")
        body = resp.json()
        assert len(body) == 2
        assert body[0]["start_date"] == (today - timedelta(days=5)).isoformat()
