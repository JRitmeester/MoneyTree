"""Tests for the salary allocation waterfall.

Spec: docs/superpowers/specs/2026-08-28-salary-allocation-design.md,
section "Allocation calculation" (binding).
"""
from datetime import date

from sqlalchemy.orm import Session

from app.models import AllocationBucket, Category, RecurringPayment, RecurringPaymentOccurrence
from app.services.salary_allocator import compute_allocation

from .conftest import make_transaction


def _salary(
    db: Session, *, expected_amount: float = 3000, occurrence: tuple[date, float] | None = None
) -> RecurringPayment:
    payment = RecurringPayment(
        merchant_pattern="Salary",
        name="Salary",
        expected_amount=expected_amount,
        cadence="monthly",
        expected_day=22,
        anchor_date=date(2026, 7, 22),
        status="confirmed",
        is_income=True,
    )
    db.add(payment)
    db.flush()
    if occurrence is not None:
        occ_date, occ_amount = occurrence
        tx = make_transaction(db, bedrag=occ_amount, datum=occ_date, naam="Salary")
        db.add(
            RecurringPaymentOccurrence(
                recurring_payment_id=payment.id,
                transaction_id=tx.id,
                amount=occ_amount,
                date=occ_date,
            )
        )
    db.commit()
    return payment


def _bill(db: Session, *, name: str, amount: float, day: int) -> None:
    db.add(
        RecurringPayment(
            merchant_pattern=name,
            name=name,
            expected_amount=amount,
            cadence="monthly",
            expected_day=day,
            anchor_date=date(2026, 7, day),
            status="confirmed",
            is_income=False,
        )
    )
    db.commit()


def _bucket(db: Session, *, name: str, rule_type: str, value: float, position: int,
            is_active: bool = True, category_id: int | None = None) -> AllocationBucket:
    bucket = AllocationBucket(
        name=name, rule_type=rule_type, value=value, position=position,
        is_active=is_active, category_id=category_id,
    )
    db.add(bucket)
    db.commit()
    return bucket


class TestAllocatorStates:
    def test_no_confirmed_salary(self, db: Session):
        result = compute_allocation(db, buffer_pct=10.0, today=date(2026, 8, 25))
        assert result.salary_confirmed is False
        assert result.message == "Confirm your salary as recurring income first"
        assert result.lines == []

    def test_actual_basis_uses_latest_occurrence(self, db: Session):
        # Actual salary 3200 differs from expected 3000; latest occurrence
        # 2026-08-21 (Friday, the shifted-back 22nd).
        _salary(db, expected_amount=3000, occurrence=(date(2026, 8, 21), 3200.0))
        result = compute_allocation(db, buffer_pct=10.0, today=date(2026, 8, 25))
        assert result.basis == "actual"
        assert result.payday == date(2026, 8, 21)
        assert result.salary_amount == 3200.0

    def test_expected_basis_without_occurrences(self, db: Session):
        _salary(db, expected_amount=3000, occurrence=None)
        result = compute_allocation(db, buffer_pct=10.0, today=date(2026, 8, 20))
        assert result.basis == "expected"
        # Raw 2026-08-22 is a Saturday; income shifts backward to Friday.
        assert result.payday == date(2026, 8, 21)
        assert result.salary_amount == 3000.0

    def test_stale_anchor_warns(self, db: Session):
        # Latest occurrence 2026-06-22: the period ended 2026-07-22, long
        # before "today". The plan still computes but warns.
        _salary(db, occurrence=(date(2026, 6, 22), 3000.0))
        result = compute_allocation(db, buffer_pct=10.0, today=date(2026, 8, 25))
        assert result.basis == "actual"
        assert any("2026-06-22" in w and "newer salary" in w for w in result.warnings)


class TestWaterfall:
    def test_fixed_and_percent_rows_sum_to_salary(self, db: Session):
        _salary(db, occurrence=(date(2026, 8, 21), 3200.0))
        # Rent lands 2026-09-01, comfortably transferable: bills pot
        # covers it with the 10% buffer, nothing kept in checking.
        _bill(db, name="Rent", amount=-900, day=1)
        _bucket(db, name="Investing", rule_type="fixed", value=300, position=0)
        _bucket(db, name="Long-term", rule_type="percent", value=50, position=1)

        result = compute_allocation(db, buffer_pct=10.0, today=date(2026, 8, 25))

        assert result.bills_pot == 990.0  # 900 * 1.1
        assert result.kept_in_checking == 0.0
        amounts = {l.name: l.amount for l in result.lines}
        assert amounts["Investing"] == 300.0
        # remainder after pot and fixed: 3200 - 990 - 300 = 1910; 50% = 955
        assert amounts["Long-term"] == 955.0
        assert result.free_to_spend == 955.0
        total = result.bills_pot + result.kept_in_checking + sum(amounts.values()) + result.free_to_spend
        assert round(total, 2) == 3200.0
        assert result.warnings == []
        assert all(l.shortfall is False for l in result.lines)

    def test_percent_flooring_leftover_lands_in_free(self, db: Session):
        _salary(db, occurrence=(date(2026, 8, 21), 1000.0))
        for i, name in enumerate(["A", "B", "C"]):
            _bucket(db, name=name, rule_type="percent", value=33.33, position=i)

        result = compute_allocation(db, buffer_pct=0.0, today=date(2026, 8, 25))

        # floor_to_cent(1000 * 0.3333) = 333.30 each
        assert [l.amount for l in result.lines] == [333.3, 333.3, 333.3]
        assert result.free_to_spend == round(1000 - 3 * 333.3, 2)
        total = sum(l.amount for l in result.lines) + result.free_to_spend
        assert round(total, 2) == 1000.0

    def test_fixed_shortfall_fills_in_position_order(self, db: Session):
        _salary(db, occurrence=(date(2026, 8, 21), 500.0))
        _bucket(db, name="First", rule_type="fixed", value=300, position=0)
        _bucket(db, name="Second", rule_type="fixed", value=300, position=1)
        _bucket(db, name="Share", rule_type="percent", value=50, position=2)

        result = compute_allocation(db, buffer_pct=0.0, today=date(2026, 8, 25))

        by_name = {l.name: l for l in result.lines}
        assert by_name["First"].amount == 300.0
        assert by_name["First"].shortfall is False
        assert by_name["Second"].amount == 200.0
        assert by_name["Second"].shortfall is True
        assert by_name["Share"].amount == 0.0
        assert by_name["Share"].shortfall is False
        assert result.free_to_spend == 0.0
        shortfall_warnings = [w for w in result.warnings if "Second" in w]
        assert len(shortfall_warnings) == 1

    def test_salary_below_bills_pot_clamps_all(self, db: Session):
        _salary(db, occurrence=(date(2026, 8, 21), 500.0))
        _bill(db, name="Rent", amount=-900, day=1)
        _bucket(db, name="Investing", rule_type="fixed", value=300, position=0)

        result = compute_allocation(db, buffer_pct=0.0, today=date(2026, 8, 25))

        assert result.bills_pot == 900.0
        assert all(l.amount == 0.0 for l in result.lines)
        assert result.free_to_spend == 0.0
        assert any("does not cover" in w for w in result.warnings)

    def test_inactive_buckets_omitted(self, db: Session):
        _salary(db, occurrence=(date(2026, 8, 21), 1000.0))
        _bucket(db, name="Paused", rule_type="fixed", value=300, position=0, is_active=False)
        _bucket(db, name="Live", rule_type="fixed", value=100, position=1)

        result = compute_allocation(db, buffer_pct=0.0, today=date(2026, 8, 25))
        assert [l.name for l in result.lines] == ["Live"]

    def test_category_name_is_full_path(self, db: Session):
        parent = Category(name="Sparen", category_type="expense")
        db.add(parent)
        db.flush()
        child = Category(name="Lange termijn", category_type="expense", parent_id=parent.id)
        db.add(child)
        db.commit()

        _salary(db, occurrence=(date(2026, 8, 21), 1000.0))
        _bucket(db, name="LT", rule_type="fixed", value=100, position=0, category_id=child.id)

        result = compute_allocation(db, buffer_pct=0.0, today=date(2026, 8, 25))
        assert result.lines[0].category_name == "Sparen > Lange termijn"
        assert result.lines[0].category_id == child.id
