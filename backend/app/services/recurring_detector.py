"""Recurring-payment detection.

Groups non-internal transactions by counterparty IBAN (preferred) or
normalized merchant name, classifies the group's cadence (monthly,
four_weekly, yearly) from the gaps between occurrences, and checks whether
the amounts are stable enough to call it a recurring payment.

Detection runs on the full transaction history each time (single-user
scale); `upsert_recurring_payments` refreshes `suggested` rows in place and
never touches `confirmed` or `dismissed` rows.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Sequence

from sqlalchemy.orm import Session

from app.models import RecurringPayment, RecurringPaymentOccurrence, Transaction
from app.services.merchant import normalize_merchant_name

# --- Detection thresholds (named constants, see spec "Recurring-payment
# detection") -----------------------------------------------------------

MIN_OCCURRENCES_MONTHLY = 3
MIN_OCCURRENCES_FOUR_WEEKLY = 3
MIN_OCCURRENCES_YEARLY = 2

MONTHLY_GAP_MIN_DAYS = 26
MONTHLY_GAP_MAX_DAYS = 36
FOUR_WEEKLY_GAP_MIN_DAYS = 26
FOUR_WEEKLY_GAP_MAX_DAYS = 30
YEARLY_GAP_MIN_DAYS = 350
YEARLY_GAP_MAX_DAYS = 380

DAY_OF_MONTH_TOLERANCE = 4

AMOUNT_TOLERANCE_FRACTION = 0.15
AMOUNT_QUALIFYING_FRACTION = 0.75
DEFAULT_AMOUNT_TOLERANCE = 0.15


@dataclass(frozen=True)
class CadenceResult:
    cadence: str  # "monthly" | "four_weekly" | "yearly"
    expected_day: int | None
    anchor_date: date


@dataclass(frozen=True)
class Occurrence:
    transaction_id: int
    amount: float
    date: date


@dataclass(frozen=True)
class RecurringCandidate:
    group_key: str
    counterparty_iban: str | None
    merchant_pattern: str
    name: str
    cadence: str
    expected_day: int | None
    anchor_date: date
    expected_amount: float
    amount_tolerance: float
    is_income: bool
    occurrences: tuple[Occurrence, ...] = field(default_factory=tuple)


def _gaps(dates: Sequence[date]) -> list[int]:
    return [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]


def _day_of_month_stable(dates: Sequence[date], median_day: float) -> bool:
    return all(abs(d.day - median_day) <= DAY_OF_MONTH_TOLERANCE for d in dates)


def detect_cadence(dates: Sequence[date]) -> CadenceResult | None:
    """Classify the cadence of a series of occurrence dates.

    See spec "Recurring-payment detection" for the exact rules: monthly
    needs 3+ occurrences with a 26-36 day median gap and a day-of-month
    stable within +/-4; four_weekly needs 3+ occurrences with a 26-30 day
    median gap and a drifting day-of-month; yearly needs 2+ occurrences
    with a 350-380 day median gap.
    """
    ordered = sorted(dates)

    if len(ordered) >= MIN_OCCURRENCES_MONTHLY:
        gaps = _gaps(ordered)
        median_gap = statistics.median(gaps)
        days_of_month = [d.day for d in ordered]
        median_day = statistics.median(days_of_month)

        if MONTHLY_GAP_MIN_DAYS <= median_gap <= MONTHLY_GAP_MAX_DAYS and _day_of_month_stable(
            ordered, median_day
        ):
            return CadenceResult(
                cadence="monthly", expected_day=round(median_day), anchor_date=ordered[-1]
            )

        if FOUR_WEEKLY_GAP_MIN_DAYS <= median_gap <= FOUR_WEEKLY_GAP_MAX_DAYS:
            return CadenceResult(
                cadence="four_weekly", expected_day=None, anchor_date=ordered[-1]
            )

    if len(ordered) >= MIN_OCCURRENCES_YEARLY:
        gaps = _gaps(ordered)
        median_gap = statistics.median(gaps)
        if YEARLY_GAP_MIN_DAYS <= median_gap <= YEARLY_GAP_MAX_DAYS:
            return CadenceResult(
                cadence="yearly", expected_day=ordered[-1].day, anchor_date=ordered[-1]
            )

    return None


def median_amount(amounts: Iterable[float]) -> float:
    return statistics.median(abs(a) for a in amounts)


def is_amount_outlier(amount: float, median: float, tolerance: float) -> bool:
    """Whether a single occurrence's amount falls outside tolerance of the
    group median. Computed on demand (e.g. for display); never persisted."""
    if median == 0:
        return True
    return abs(abs(amount) - median) > tolerance * median


def amounts_qualify(amounts: Sequence[float]) -> bool:
    """A candidate qualifies if at least 75% of its occurrences fall within
    15% of the median amount. Outliers (e.g. a settlement month) flag but
    don't disqualify the group."""
    if not amounts:
        return False
    median = median_amount(amounts)
    if median == 0:
        return False
    within = [a for a in amounts if not is_amount_outlier(a, median, AMOUNT_TOLERANCE_FRACTION)]
    return len(within) / len(amounts) >= AMOUNT_QUALIFYING_FRACTION


def _group_key(tx: Transaction) -> str | None:
    if tx.tegenrekening:
        return tx.tegenrekening
    name = tx.merchant_name or tx.naam
    if name:
        return normalize_merchant_name(name)
    return None


def build_candidates(transactions: Iterable[Transaction]) -> list[RecurringCandidate]:
    """Pure detection over an in-memory list of transactions: group,
    classify cadence, check the amount rule. Excludes internal transfers."""
    groups: dict[str, list[Transaction]] = {}
    for tx in transactions:
        if tx.is_internal_transfer:
            continue
        key = _group_key(tx)
        if key is None:
            continue
        groups.setdefault(key, []).append(tx)

    candidates: list[RecurringCandidate] = []
    for key, txs in groups.items():
        txs_sorted = sorted(txs, key=lambda t: t.datum)
        dates = [t.datum for t in txs_sorted]
        cadence_result = detect_cadence(dates)
        if cadence_result is None:
            continue

        amounts = [t.bedrag for t in txs_sorted]
        if not amounts_qualify(amounts):
            continue

        counterparty_iban = txs_sorted[0].tegenrekening
        merchant_pattern = "" if counterparty_iban else key
        display_name = txs_sorted[0].merchant_name or txs_sorted[0].naam or key
        expected_amount = statistics.median(amounts)
        is_income = expected_amount > 0

        occurrences = tuple(
            Occurrence(transaction_id=t.id, amount=t.bedrag, date=t.datum) for t in txs_sorted
        )

        candidates.append(
            RecurringCandidate(
                group_key=key,
                counterparty_iban=counterparty_iban,
                merchant_pattern=merchant_pattern,
                name=display_name,
                cadence=cadence_result.cadence,
                expected_day=cadence_result.expected_day,
                anchor_date=cadence_result.anchor_date,
                expected_amount=expected_amount,
                amount_tolerance=DEFAULT_AMOUNT_TOLERANCE,
                is_income=is_income,
                occurrences=occurrences,
            )
        )

    return candidates


def _row_key(row: RecurringPayment) -> str:
    return row.counterparty_iban if row.counterparty_iban else row.merchant_pattern


def detect_recurring_payments(db: Session) -> list[RecurringCandidate]:
    """Run detection over the full transaction history in the database."""
    transactions = db.query(Transaction).all()
    return build_candidates(transactions)


def upsert_recurring_payments(
    db: Session, candidates: Sequence[RecurringCandidate]
) -> list[RecurringPayment]:
    """Refresh `suggested` recurring_payments rows in place, matched by
    group key. Never creates a competing row for a group that already has a
    confirmed or dismissed pattern, and never modifies confirmed/dismissed
    rows."""
    existing_rows = db.query(RecurringPayment).all()
    by_key = {_row_key(row): row for row in existing_rows}

    result: list[RecurringPayment] = []
    for candidate in candidates:
        row = by_key.get(candidate.group_key)
        if row is not None and row.status != "suggested":
            continue

        if row is None:
            row = RecurringPayment(status="suggested")
            db.add(row)

        row.merchant_pattern = candidate.merchant_pattern
        row.counterparty_iban = candidate.counterparty_iban
        row.name = candidate.name
        row.expected_amount = candidate.expected_amount
        row.amount_tolerance = candidate.amount_tolerance
        row.cadence = candidate.cadence
        row.expected_day = candidate.expected_day
        row.anchor_date = candidate.anchor_date
        row.is_income = candidate.is_income
        db.flush()

        db.query(RecurringPaymentOccurrence).filter_by(recurring_payment_id=row.id).delete()
        for occ in candidate.occurrences:
            db.add(
                RecurringPaymentOccurrence(
                    recurring_payment_id=row.id,
                    transaction_id=occ.transaction_id,
                    amount=occ.amount,
                    date=occ.date,
                )
            )

        result.append(row)

    db.flush()
    return result
