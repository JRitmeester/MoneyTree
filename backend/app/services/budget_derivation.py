"""Derived budget lines.

Materializes system-owned budget lines from the two authoritative sources:
confirmed recurring payments (Fixed section, source "recurring") and
allocation buckets (Savings section, source "allocation"). Called lazily
by the budget router on read/create/update; only periods that have not
ended are ever touched, so history stays frozen.

Spec: docs/superpowers/specs/2026-08-28-derived-budget-lines-design.md.
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AllocationBucket, AppSetting, Budget, BudgetLine, Category,
    RecurringPayment, RecurringPaymentOccurrence,
)
from .cashflow_advisor import DEFAULT_BUFFER_PCT, compute_advice, occurrences_in_range
from .recurring_detector import find_salary_payment_id

logger = logging.getLogger(__name__)


def _buffer_pct(db: Session) -> float:
    row = db.get(AppSetting, "buffer_pct")
    return float(row.value) if row else DEFAULT_BUFFER_PCT


def _fixed_targets(db: Session, budget: Budget) -> dict[int, float]:
    """category_id -> summed absolute amount of confirmed recurring-payment
    occurrences (expenses AND income, e.g. the salary) projected into the
    period. Income and expense payments never share a category in practice;
    both carry source "recurring"."""
    payments = db.execute(
        select(RecurringPayment).where(
            RecurringPayment.status == "confirmed",
            RecurringPayment.category_id.is_not(None),
        )
    ).scalars().all()

    targets: dict[int, float] = {}
    for payment in payments:
        try:
            occurrences = occurrences_in_range(
                payment, budget.start_date, budget.end_date, shift_weekend=True
            )
        except Exception:
            logger.exception("Skipping fixed derivation for payment %s", payment.id)
            continue
        if occurrences:
            amount = abs(payment.expected_amount) * len(occurrences)
            targets[payment.category_id] = round(targets.get(payment.category_id, 0.0) + amount, 2)
    return targets


def _paydays_in_period(db: Session, budget: Budget) -> list[tuple[date, float]]:
    """(payday, salary amount) pairs inside [start_date, end_date): actual
    salary occurrences when any exist in the period, else projected shifted
    paydays at the expected amount."""
    salary_id = find_salary_payment_id(db)
    if salary_id is None:
        return []
    salary = db.get(RecurringPayment, salary_id)

    occurrences = db.execute(
        select(RecurringPaymentOccurrence)
        .where(
            RecurringPaymentOccurrence.recurring_payment_id == salary_id,
            RecurringPaymentOccurrence.date >= budget.start_date,
            RecurringPaymentOccurrence.date < budget.end_date,
        )
        .order_by(RecurringPaymentOccurrence.date)
    ).scalars().all()
    if occurrences:
        return [(o.date, abs(o.amount)) for o in occurrences if abs(o.amount) > 0]

    projected = occurrences_in_range(
        salary, budget.start_date, budget.end_date, shift_weekend=True
    )
    return [(d, abs(salary.expected_amount)) for d in projected]


def _savings_targets(db: Session, budget: Budget) -> dict[int, float]:
    """category_id -> summed INTENDED contribution from active, linked
    allocation buckets over the period's payday(s).

    Intent, not outcome (user decision 2026-08-28): the budget is a plan
    document, so fixed buckets derive their full configured value even in
    a month whose salary cannot fund them; the shortfall story is told on
    the cash-flow card. Percent buckets derive their share of the
    post-bills, post-fixed base (floored at zero), which is their intent
    by definition."""
    buckets = db.execute(
        select(AllocationBucket)
        .where(AllocationBucket.is_active.is_(True))
        .order_by(AllocationBucket.position, AllocationBucket.id)
    ).scalars().all()
    if not any(b.category_id is not None for b in buckets):
        return {}

    import math

    buffer_pct = _buffer_pct(db)
    total_fixed = sum(b.value for b in buckets if b.rule_type == "fixed")

    targets: dict[int, float] = {}
    for payday, salary_amount in _paydays_in_period(db, budget):
        try:
            advice = compute_advice(db, buffer_pct, anchor_payday=payday)
            earmarked = (advice.sweep_amount or 0.0) + advice.keep_in_checking
        except Exception:
            logger.exception("Skipping savings derivation for payday %s", payday)
            continue
        percent_base = max(0.0, salary_amount - earmarked - total_fixed)
        for bucket in buckets:
            if bucket.category_id is None:
                continue
            if bucket.rule_type == "fixed":
                amount = bucket.value
            else:
                amount = math.floor(percent_base * bucket.value / 100 * 100 + 1e-9) / 100
            if amount > 0:
                targets[bucket.category_id] = round(
                    targets.get(bucket.category_id, 0.0) + amount, 2
                )
    return targets


def compute_derived_targets(db: Session, budget: Budget) -> dict[int, tuple[float, str]]:
    """category_id -> (amount, source) for everything that derives in this
    period. Precedence when both sources produce the same category:
    savings-type categories prefer "allocation", others "recurring"."""
    fixed = _fixed_targets(db, budget)
    savings = _savings_targets(db, budget)

    cat_types = {
        c.id: c.category_type
        for c in db.execute(
            select(Category).where(Category.id.in_(set(fixed) | set(savings)))
        ).scalars().all()
    }

    targets: dict[int, tuple[float, str]] = {}
    for cat_id, amount in fixed.items():
        targets[cat_id] = (amount, "recurring")
    for cat_id, amount in savings.items():
        if cat_id in targets and cat_types.get(cat_id) != "savings":
            continue  # expense-type category with both: recurring wins
        targets[cat_id] = (amount, "allocation")
    return targets


def deriving_category_ids(db: Session, budget: Budget, today: date | None = None) -> dict[int, str]:
    """category_id -> source for categories that currently derive in this
    period; empty for frozen (ended) periods."""
    today = today or date.today()
    if budget.end_date < today:
        return {}
    return {cat_id: source for cat_id, (_, source) in compute_derived_targets(db, budget).items()}


def refresh_derived_lines(db: Session, budget: Budget, today: date | None = None) -> None:
    """Upsert derived lines for `budget` to match the current authoritative
    state. Does not commit; the caller owns the transaction. Never raises
    for derivation problems (they are logged and skipped). Periods that
    have already ended are never touched."""
    today = today or date.today()
    if budget.end_date < today:
        return

    targets = compute_derived_targets(db, budget)

    lines_by_category = {
        l.category_id: l
        for l in db.execute(
            select(BudgetLine).where(BudgetLine.budget_id == budget.id)
        ).scalars().all()
    }

    for cat_id, (amount, source) in targets.items():
        existing = lines_by_category.get(cat_id)
        if existing is not None:
            # One-way adoption: a manual line whose category now derives is
            # taken over (amount superseded, source flipped).
            existing.amount = amount
            existing.source = source
        else:
            db.add(BudgetLine(
                budget_id=budget.id, category_id=cat_id, amount=amount, source=source,
            ))

    for cat_id, line in lines_by_category.items():
        if line.source != "manual" and cat_id not in targets:
            db.delete(line)
