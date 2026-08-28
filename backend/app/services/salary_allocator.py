"""Salary allocation waterfall.

Divides the salary of the current pay period over the recurring-bills pot
(from the anchored transfer advisor), the configured allocation buckets
(fixed euro amounts first, then percentages of what remains), and a final
free-to-spend remainder. Plan-only: nothing is persisted here.

Spec: docs/superpowers/specs/2026-08-28-salary-allocation-design.md,
section "Allocation calculation" (binding).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AllocationBucket, Category, RecurringPayment, RecurringPaymentOccurrence
from .category_paths import full_category_path
from .cashflow_advisor import _next_payday_after, compute_advice
from .recurring_detector import (
    find_salary_payment_id,
    next_expected_date,
    shift_expected_date,
)

# Amounts within this of the configured value count as fully funded, so
# float noise can never flag a phantom shortfall.
_EPSILON = 0.005


@dataclass(frozen=True)
class AllocationLine:
    bucket_id: int
    name: str
    rule_type: str
    value: float
    amount: float
    category_id: int | None
    category_name: str | None
    shortfall: bool


@dataclass(frozen=True)
class SalaryAllocation:
    salary_confirmed: bool
    message: str | None = None
    payday: date | None = None
    basis: str | None = None  # "actual" | "expected"
    salary_amount: float | None = None
    bills_pot: float = 0.0
    kept_in_checking: float = 0.0
    free_to_spend: float = 0.0
    lines: list[AllocationLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _floor_to_cent(x: float) -> float:
    return math.floor(x * 100 + 1e-9) / 100


def _latest_occurrence(db: Session, payment_id: int) -> RecurringPaymentOccurrence | None:
    return db.execute(
        select(RecurringPaymentOccurrence)
        .where(RecurringPaymentOccurrence.recurring_payment_id == payment_id)
        .order_by(RecurringPaymentOccurrence.date.desc(), RecurringPaymentOccurrence.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _unconfirmed() -> SalaryAllocation:
    return SalaryAllocation(
        salary_confirmed=False,
        message="Confirm your salary as recurring income first",
    )


def compute_allocation(db: Session, buffer_pct: float, today: date | None = None) -> SalaryAllocation:
    today = today or date.today()

    salary_id = find_salary_payment_id(db)
    if salary_id is None:
        return _unconfirmed()
    salary: RecurringPayment = db.get(RecurringPayment, salary_id)

    warnings: list[str] = []

    # Anchor: the salary most recently received (actual amount); before any
    # occurrence exists, preview the upcoming expected payday instead.
    occurrence = _latest_occurrence(db, salary_id)
    if occurrence is not None and abs(occurrence.amount) > 0:
        anchor = occurrence.date
        salary_amount = round(abs(occurrence.amount), 2)
        basis = "actual"
    else:
        raw = next_expected_date(salary)
        if raw is None:
            return _unconfirmed()
        anchor = shift_expected_date(raw, salary.cadence, salary.is_income)
        salary_amount = round(abs(salary.expected_amount), 2)
        basis = "expected"
        if occurrence is not None:
            warnings.append(
                "The latest salary transaction has a zero amount; using the expected amount instead"
            )

    # Stale anchor: the anchored period already ended without a newer salary.
    next_payday = shift_expected_date(
        _next_payday_after(salary, anchor), salary.cadence, salary.is_income
    )
    if basis == "actual" and next_payday < today:
        warnings.append(
            f"This plan is based on the salary received on {anchor.isoformat()}; "
            "a newer salary may not be imported yet"
        )

    advice = compute_advice(db, buffer_pct, today=today, anchor_payday=anchor)
    bills_pot = round(advice.sweep_amount or 0.0, 2)
    kept_in_checking = round(advice.keep_in_checking, 2)

    buckets = db.execute(
        select(AllocationBucket)
        .where(AllocationBucket.is_active.is_(True))
        .order_by(AllocationBucket.position, AllocationBucket.id)
    ).scalars().all()

    cat_by_id = (
        {c.id: c for c in db.execute(select(Category)).scalars().all()}
        if any(b.category_id is not None for b in buckets)
        else {}
    )

    def _line(bucket: AllocationBucket, amount: float, shortfall: bool) -> AllocationLine:
        return AllocationLine(
            bucket_id=bucket.id,
            name=bucket.name,
            rule_type=bucket.rule_type,
            value=bucket.value,
            amount=round(amount, 2),
            category_id=bucket.category_id,
            category_name=(
                full_category_path(bucket.category_id, cat_by_id)
                if bucket.category_id is not None
                else None
            ),
            shortfall=shortfall,
        )

    remaining = round(salary_amount - bills_pot - kept_in_checking, 2)
    lines: list[AllocationLine] = []

    if remaining < 0:
        # The salary does not even cover the recurring bills: every bucket
        # is clamped to zero and nothing is free to spend.
        warnings.append(
            "This salary does not cover the recurring bills; nothing is left to allocate"
        )
        lines = [_line(b, 0.0, shortfall=b.rule_type == "fixed") for b in buckets]
        return SalaryAllocation(
            salary_confirmed=True,
            payday=anchor,
            basis=basis,
            salary_amount=salary_amount,
            bills_pot=bills_pot,
            kept_in_checking=kept_in_checking,
            free_to_spend=0.0,
            lines=lines,
            warnings=warnings,
        )

    shortfall_warned = False
    for bucket in buckets:
        if bucket.rule_type != "fixed":
            continue
        amount = round(min(bucket.value, remaining), 2)
        shortfall = amount < bucket.value - _EPSILON
        if shortfall and not shortfall_warned:
            warnings.append(f"Not enough left to fully fund '{bucket.name}'")
            shortfall_warned = True
        lines.append(_line(bucket, amount, shortfall))
        remaining = round(remaining - amount, 2)

    percent_base = remaining
    for bucket in buckets:
        if bucket.rule_type != "percent":
            continue
        amount = _floor_to_cent(percent_base * bucket.value / 100)
        lines.append(_line(bucket, amount, shortfall=False))

    # Preserve configured bucket order in the output (fixed and percent
    # buckets may interleave in position order).
    order = {b.id: i for i, b in enumerate(buckets)}
    lines.sort(key=lambda l: order[l.bucket_id])

    allocated = sum(l.amount for l in lines)
    free_to_spend = max(0.0, round(salary_amount - bills_pot - kept_in_checking - allocated, 2))

    return SalaryAllocation(
        salary_confirmed=True,
        payday=anchor,
        basis=basis,
        salary_amount=salary_amount,
        bills_pot=bills_pot,
        kept_in_checking=kept_in_checking,
        free_to_spend=free_to_spend,
        lines=lines,
        warnings=warnings,
    )
