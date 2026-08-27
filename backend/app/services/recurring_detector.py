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
from datetime import date, timedelta
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
# Gaps must be tightly clustered around ~28 days for a four_weekly call: this
# is the simpler, robust stand-in for "day-of-month drifts consistently"
# (a steady drift produces near-identical gaps; erratic noise does not).
FOUR_WEEKLY_GAP_SPREAD_MAX_DAYS = 4
YEARLY_GAP_MIN_DAYS = 350
YEARLY_GAP_MAX_DAYS = 380

DAY_OF_MONTH_TOLERANCE = 4

AMOUNT_TOLERANCE_FRACTION = 0.15
AMOUNT_QUALIFYING_FRACTION = 0.75
DEFAULT_AMOUNT_TOLERANCE = 0.15

# --- Lifecycle constants (import-time matching, drift, notices; see spec
# "Recurring-payment detection" Lifecycle paragraph) ---------------------

DATE_MATCH_WINDOW_DAYS = 5
POSSIBLY_MISSED_GRACE_DAYS = 5
# expected_amount drifts partially (not fully) toward each newly matched
# occurrence's amount, so a genuinely changed amount still shows up as a
# deviation from expected_amount on read (the "amount changed" notice),
# rather than the tracked expectation snapping to match every payment. Drift
# only applies to occurrences within amount_tolerance (see
# match_new_transactions); out-of-tolerance occurrences never drift it.
AMOUNT_DRIFT_ALPHA = 0.3
# Two-band matching (spec-owner ruling, 2026-08-28): a same-group,
# same-date-window transaction matches as an occurrence as long as it falls
# within this wide band of expected_amount, even if it's outside
# amount_tolerance (in which case it surfaces an amount_changed notice
# instead of drifting expected_amount). Beyond the wide band it is not
# treated as an occurrence at all (e.g. a one-off large fee to the same
# IBAN is not "this recurring payment changed price").
MATCH_WIDE_BAND = 0.5
# After this many consecutive out-of-tolerance occurrences on the same side
# (all above or all below expected_amount), expected_amount snaps to their
# median instead of continuing to notice indefinitely (price-increase
# acceptance).
CONSECUTIVE_SNAP_COUNT = 3


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

        gap_spread = max(gaps) - min(gaps)
        if (
            FOUR_WEEKLY_GAP_MIN_DAYS <= median_gap <= FOUR_WEEKLY_GAP_MAX_DAYS
            and gap_spread <= FOUR_WEEKLY_GAP_SPREAD_MAX_DAYS
        ):
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
    rows. A `suggested` row whose group key no longer appears in this run's
    candidates is removed, keeping the suggestion list clean; confirmed and
    dismissed rows are kept regardless (the user's decision persists even if
    the pattern temporarily drops out of detection)."""
    existing_rows = db.query(RecurringPayment).all()
    by_key = {_row_key(row): row for row in existing_rows}
    current_keys = {candidate.group_key for candidate in candidates}

    for key, row in by_key.items():
        if row.status == "suggested" and key not in current_keys:
            db.delete(row)
    db.flush()

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


def amount_deviates(amount: float, expected_amount: float, tolerance: float) -> bool:
    """Whether `amount` falls outside `tolerance` of `expected_amount`.

    Unlike `is_amount_outlier` (which compares against an already-abs
    median), `expected_amount` here is a signed value (positive for income,
    negative for expenses), so it is abs'd before comparison."""
    median = abs(expected_amount)
    if median == 0:
        return True
    return abs(abs(amount) - median) > tolerance * median


def _add_months(base: date, months: int, day: int) -> date:
    """Add `months` calendar months to `base`, then set the day-of-month to
    `day`, clamped to the last valid day of the resulting month."""
    month_index = base.month - 1 + months
    year = base.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp to the last day of the target month.
    if month == 12:
        days_in_month = (date(year + 1, 1, 1) - date(year, 12, 1)).days
    else:
        days_in_month = (date(year, month + 1, 1) - date(year, month, 1)).days
    return date(year, month, min(day, days_in_month))


def next_expected_date(payment: RecurringPayment) -> date | None:
    """The next occurrence date expected after `payment.anchor_date`.

    monthly/yearly step from `expected_day`; four_weekly steps 28 days from
    the anchor. Returns None if the cadence lacks the data needed (should
    not happen for a fully-detected row)."""
    if payment.cadence == "four_weekly":
        return payment.anchor_date + timedelta(days=28)
    if payment.cadence == "monthly" and payment.expected_day is not None:
        return _add_months(payment.anchor_date, 1, payment.expected_day)
    if payment.cadence == "yearly" and payment.expected_day is not None:
        return _add_months(payment.anchor_date, 12, payment.expected_day)
    return None


def backfill_occurrences(db: Session, payment: RecurringPayment) -> None:
    """Rebuild `payment`'s occurrences from the full transaction history,
    matched by the same group key used by detection. Called on confirm so a
    just-confirmed pattern has its complete history recorded, independent of
    whatever the last detector run happened to populate."""
    key = _row_key(payment)
    transactions = db.query(Transaction).all()
    matches = [
        tx for tx in transactions if not tx.is_internal_transfer and _group_key(tx) == key
    ]
    matches.sort(key=lambda t: t.datum)

    db.query(RecurringPaymentOccurrence).filter_by(recurring_payment_id=payment.id).delete()
    for tx in matches:
        db.add(
            RecurringPaymentOccurrence(
                recurring_payment_id=payment.id,
                transaction_id=tx.id,
                amount=tx.bedrag,
                date=tx.datum,
            )
        )
    if matches:
        payment.anchor_date = matches[-1].datum
    db.flush()


def _maybe_snap_expected_amount(db: Session, row: RecurringPayment) -> None:
    """After CONSECUTIVE_SNAP_COUNT consecutive out-of-tolerance occurrences
    on the same side (all above or all below expected_amount), snap
    expected_amount to their median. Accepts a sustained price change
    instead of raising an amount_changed notice indefinitely."""
    recent = (
        db.query(RecurringPaymentOccurrence)
        .filter_by(recurring_payment_id=row.id)
        .order_by(RecurringPaymentOccurrence.date.desc())
        .limit(CONSECUTIVE_SNAP_COUNT)
        .all()
    )
    if len(recent) < CONSECUTIVE_SNAP_COUNT:
        return
    if not all(amount_deviates(o.amount, row.expected_amount, row.amount_tolerance) for o in recent):
        return

    expected_median = abs(row.expected_amount)
    sides = {1 if abs(o.amount) > expected_median else -1 for o in recent}
    if len(sides) != 1:
        return

    row.expected_amount = statistics.median(o.amount for o in recent)


def match_new_transactions(db: Session, transactions: Sequence[Transaction]) -> int:
    """Match newly-imported transactions against confirmed recurring
    patterns (spec Lifecycle paragraph, two-band ruling 2026-08-28): same
    group key, date within +/-DATE_MATCH_WINDOW_DAYS of the expected date,
    amount within MATCH_WIDE_BAND of expected_amount. A match appends an
    occurrence and updates `anchor_date`. Within amount_tolerance, it also
    drifts `expected_amount` toward the new amount; outside tolerance (but
    still inside the wide band) expected_amount is left alone so the
    deviation surfaces as an "amount changed" notice on read, unless
    CONSECUTIVE_SNAP_COUNT consecutive same-side deviations have
    accumulated, in which case expected_amount snaps to their median.
    Beyond the wide band, the transaction is not treated as an occurrence at
    all. Returns the number of matches made."""
    confirmed = db.query(RecurringPayment).filter_by(status="confirmed").all()
    if not confirmed:
        return 0

    by_key: dict[str, RecurringPayment] = {_row_key(row): row for row in confirmed}
    already_linked: set[int] = {
        occ.transaction_id for row in confirmed for occ in row.occurrences
    }

    matches = 0
    for tx in transactions:
        if tx.is_internal_transfer or tx.id in already_linked:
            continue
        key = _group_key(tx)
        if key is None:
            continue
        row = by_key.get(key)
        if row is None:
            continue
        expected_date = next_expected_date(row)
        if expected_date is None:
            continue
        if abs((tx.datum - expected_date).days) > DATE_MATCH_WINDOW_DAYS:
            continue
        if amount_deviates(tx.bedrag, row.expected_amount, MATCH_WIDE_BAND):
            continue

        db.add(
            RecurringPaymentOccurrence(
                recurring_payment_id=row.id,
                transaction_id=tx.id,
                amount=tx.bedrag,
                date=tx.datum,
            )
        )
        db.flush()
        row.anchor_date = tx.datum

        if amount_deviates(tx.bedrag, row.expected_amount, row.amount_tolerance):
            _maybe_snap_expected_amount(db, row)
        else:
            row.expected_amount = row.expected_amount + AMOUNT_DRIFT_ALPHA * (
                tx.bedrag - row.expected_amount
            )

        already_linked.add(tx.id)
        matches += 1

    db.flush()
    return matches


def compute_notices(db: Session, today: date | None = None) -> list[dict]:
    """Notices computed on read from confirmed recurring payments (spec
    Lifecycle paragraph): "amount_changed" when the latest occurrence
    deviates from `expected_amount` beyond `amount_tolerance`;
    "possibly_missed" when the expected date has passed by
    POSSIBLY_MISSED_GRACE_DAYS or more with no matching occurrence."""
    today = today or date.today()
    notices: list[dict] = []

    confirmed = db.query(RecurringPayment).filter_by(status="confirmed").all()
    for payment in confirmed:
        occurrences = sorted(payment.occurrences, key=lambda o: o.date)

        if occurrences:
            latest = occurrences[-1]
            if amount_deviates(latest.amount, payment.expected_amount, payment.amount_tolerance):
                notices.append(
                    {
                        "recurring_payment_id": payment.id,
                        "name": payment.name,
                        "type": "amount_changed",
                        "detail": (
                            f"Latest amount {latest.amount:.2f} deviates from expected "
                            f"{payment.expected_amount:.2f}"
                        ),
                        "date": latest.date,
                    }
                )

        expected = next_expected_date(payment)
        if expected is not None and (today - expected).days >= POSSIBLY_MISSED_GRACE_DAYS:
            notices.append(
                {
                    "recurring_payment_id": payment.id,
                    "name": payment.name,
                    "type": "possibly_missed",
                    "detail": f"Expected on {expected.isoformat()}, no matching transaction yet",
                    "date": expected,
                }
            )

    return notices
