"""Tests for derived budget lines.

Spec: docs/superpowers/specs/2026-08-28-derived-budget-lines-design.md,
sections "Core mechanism", "Refresh rules", both "Derivation" sections.
"""
from datetime import date

from sqlalchemy.orm import Session

from app.models import (
    AllocationBucket, Budget, BudgetLine, Category,
    RecurringPayment, RecurringPaymentOccurrence,
)
from app.services.budget_derivation import refresh_derived_lines

from .conftest import make_transaction

TODAY = date(2026, 8, 25)


def _budget(db: Session, start: date = date(2026, 8, 1), end: date = date(2026, 9, 1)) -> Budget:
    budget = Budget(start_date=start, end_date=end)
    db.add(budget)
    db.commit()
    return budget


def _category(db: Session, name: str, *, category_type: str = "expense", is_fixed: bool = True) -> Category:
    cat = Category(name=name, category_type=category_type, is_fixed=is_fixed)
    db.add(cat)
    db.commit()
    return cat


def _payment(
    db: Session, *, name: str, amount: float, cadence: str = "monthly",
    expected_day: int | None = 10, anchor: date = date(2026, 7, 10),
    category_id: int | None = None, is_income: bool = False, status: str = "confirmed",
) -> RecurringPayment:
    payment = RecurringPayment(
        merchant_pattern=name, name=name, expected_amount=amount, cadence=cadence,
        expected_day=expected_day, anchor_date=anchor, status=status,
        is_income=is_income, category_id=category_id,
    )
    db.add(payment)
    db.commit()
    return payment


def _salary(db: Session, *, occurrence: tuple[date, float] | None = (date(2026, 8, 21), 3000.0)):
    payment = _payment(
        db, name="Salary", amount=3000, expected_day=22,
        anchor=date(2026, 7, 22), is_income=True,
    )
    if occurrence:
        occ_date, occ_amount = occurrence
        tx = make_transaction(db, bedrag=occ_amount, datum=occ_date, naam="Salary")
        db.add(RecurringPaymentOccurrence(
            recurring_payment_id=payment.id, transaction_id=tx.id,
            amount=occ_amount, date=occ_date,
        ))
        db.commit()
    return payment


def _bucket(db: Session, *, name: str, rule_type: str, value: float,
            category_id: int | None, position: int = 0, is_active: bool = True):
    bucket = AllocationBucket(
        name=name, rule_type=rule_type, value=value, position=position,
        category_id=category_id, is_active=is_active,
    )
    db.add(bucket)
    db.commit()
    return bucket


def _lines(db: Session, budget: Budget) -> dict[int, BudgetLine]:
    db.expire_all()
    return {l.category_id: l for l in db.query(BudgetLine).filter_by(budget_id=budget.id).all()}


class TestFixedDerivation:
    def test_monthly_payment_derives_line(self, db: Session):
        cat = _category(db, "Huur")
        _payment(db, name="Rent", amount=-1233, category_id=cat.id, expected_day=3, anchor=date(2026, 7, 3))
        budget = _budget(db)

        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()

        line = _lines(db, budget)[cat.id]
        assert line.amount == 1233.0
        assert line.source == "recurring"

    def test_four_weekly_double_occurrence_counts_twice(self, db: Session):
        cat = _category(db, "Sport")
        # Anchor 2026-08-04: occurrences 2026-08-04 and 2026-09-01... pick
        # anchor so two land inside August: 2026-08-01 + 28 = 2026-08-29.
        _payment(db, name="Gym", amount=-24.99, cadence="four_weekly",
                 expected_day=None, anchor=date(2026, 8, 1), category_id=cat.id)
        budget = _budget(db)

        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()

        assert _lines(db, budget)[cat.id].amount == round(2 * 24.99, 2)

    def test_yearly_only_in_its_month(self, db: Session):
        cat = _category(db, "Verzekering")
        _payment(db, name="Insurance", amount=-400, cadence="yearly",
                 expected_day=15, anchor=date(2025, 8, 15), category_id=cat.id)
        august = _budget(db)
        september = _budget(db, start=date(2026, 9, 1), end=date(2026, 10, 1))

        refresh_derived_lines(db, august, today=TODAY)
        refresh_derived_lines(db, september, today=TODAY)
        db.commit()

        assert _lines(db, august)[cat.id].amount == 400.0
        assert cat.id not in _lines(db, september)

    def test_uncategorized_payment_ignored(self, db: Session):
        _payment(db, name="Mystery", amount=-50, category_id=None)
        budget = _budget(db)
        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()
        assert _lines(db, budget) == {}

    def test_suggested_payment_ignored(self, db: Session):
        cat = _category(db, "Huur")
        _payment(db, name="Rent", amount=-1233, category_id=cat.id, status="suggested")
        budget = _budget(db)
        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()
        assert _lines(db, budget) == {}


class TestSavingsDerivation:
    def test_fixed_bucket_derives_per_payday(self, db: Session):
        _salary(db)
        cat = _category(db, "Autofonds", category_type="savings")
        _bucket(db, name="Car", rule_type="fixed", value=150, category_id=cat.id)
        budget = _budget(db)

        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()

        line = _lines(db, budget)[cat.id]
        assert line.amount == 150.0
        assert line.source == "allocation"

    def test_percent_bucket_uses_period_salary(self, db: Session):
        # Actual salary 3200 (differs from expected 3000); no bills, no
        # fixed buckets, buffer irrelevant (no debits): 50% of 3200 = 1600.
        _salary(db, occurrence=(date(2026, 8, 21), 3200.0))
        cat = _category(db, "Lange termijn", category_type="savings")
        _bucket(db, name="LT", rule_type="percent", value=50, category_id=cat.id)
        budget = _budget(db)

        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()

        assert _lines(db, budget)[cat.id].amount == 1600.0

    def test_projected_payday_uses_expected_amount(self, db: Session):
        # No occurrences at all: September budget projects the shifted
        # payday (2026-09-22, a Tuesday) and uses expected 3000.
        _salary(db, occurrence=None)
        cat = _category(db, "Lange termijn", category_type="savings")
        _bucket(db, name="LT", rule_type="percent", value=50, category_id=cat.id)
        budget = _budget(db, start=date(2026, 9, 1), end=date(2026, 10, 1))

        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()

        assert _lines(db, budget)[cat.id].amount == 1500.0

    def test_inactive_and_unlinked_buckets_ignored(self, db: Session):
        _salary(db)
        cat = _category(db, "Autofonds", category_type="savings")
        _bucket(db, name="Paused", rule_type="fixed", value=150, category_id=cat.id, is_active=False)
        _bucket(db, name="Unlinked", rule_type="fixed", value=99, category_id=None, position=1)
        budget = _budget(db)

        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()

        assert _lines(db, budget) == {}

    def test_no_salary_derives_no_savings(self, db: Session):
        cat = _category(db, "Autofonds", category_type="savings")
        _bucket(db, name="Car", rule_type="fixed", value=150, category_id=cat.id)
        budget = _budget(db)
        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()
        assert _lines(db, budget) == {}

    def test_savings_category_prefers_allocation_over_recurring(self, db: Session):
        _salary(db)
        cat = _category(db, "Autofonds", category_type="savings")
        _payment(db, name="Standing order", amount=-100, category_id=cat.id)
        _bucket(db, name="Car", rule_type="fixed", value=150, category_id=cat.id)
        budget = _budget(db)

        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()

        line = _lines(db, budget)[cat.id]
        assert line.source == "allocation"
        assert line.amount == 150.0


class TestRefreshRules:
    def test_manual_line_adopted_once_and_idempotent(self, db: Session):
        cat = _category(db, "Huur")
        _payment(db, name="Rent", amount=-1233, category_id=cat.id, expected_day=3, anchor=date(2026, 7, 3))
        budget = _budget(db)
        db.add(BudgetLine(budget_id=budget.id, category_id=cat.id, amount=999.0))
        db.commit()

        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()
        line = _lines(db, budget)[cat.id]
        first_id = line.id
        assert line.amount == 1233.0
        assert line.source == "recurring"

        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()
        line = _lines(db, budget)[cat.id]
        assert line.id == first_id
        assert line.amount == 1233.0

    def test_stale_derived_line_removed(self, db: Session):
        cat = _category(db, "Huur")
        payment = _payment(db, name="Rent", amount=-1233, category_id=cat.id, expected_day=3, anchor=date(2026, 7, 3))
        budget = _budget(db)
        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()
        assert cat.id in _lines(db, budget)

        payment.category_id = None
        db.commit()
        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()
        assert cat.id not in _lines(db, budget)

    def test_manual_lines_untouched(self, db: Session):
        cat = _category(db, "Boodschappen", is_fixed=False)
        budget = _budget(db)
        db.add(BudgetLine(budget_id=budget.id, category_id=cat.id, amount=350.0))
        db.commit()

        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()

        line = _lines(db, budget)[cat.id]
        assert line.amount == 350.0
        assert line.source == "manual"

    def test_past_period_frozen(self, db: Session):
        cat = _category(db, "Huur")
        _payment(db, name="Rent", amount=-1233, category_id=cat.id, expected_day=3, anchor=date(2026, 1, 3))
        budget = _budget(db, start=date(2026, 7, 1), end=date(2026, 8, 1))
        db.add(BudgetLine(budget_id=budget.id, category_id=cat.id, amount=999.0))
        db.commit()

        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()

        line = _lines(db, budget)[cat.id]
        assert line.amount == 999.0
        assert line.source == "manual"


class TestIncomeDerivation:
    def test_salary_derives_income_line(self, db: Session):
        cat = _category(db, "Salaris", category_type="income", is_fixed=False)
        _payment(
            db, name="Salary", amount=3166.17, expected_day=22,
            anchor=date(2026, 7, 22), is_income=True, category_id=cat.id,
        )
        budget = _budget(db)

        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()

        line = _lines(db, budget)[cat.id]
        assert line.amount == 3166.17
        assert line.source == "recurring"

    def test_uncategorized_income_ignored(self, db: Session):
        _payment(
            db, name="Salary", amount=3000, expected_day=22,
            anchor=date(2026, 7, 22), is_income=True, category_id=None,
        )
        budget = _budget(db)
        refresh_derived_lines(db, budget, today=TODAY)
        db.commit()
        assert _lines(db, budget) == {}
