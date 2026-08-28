"""Recurring-payment detection.

Groups non-internal transactions by counterparty IBAN (preferred) or
normalized merchant name, splits each group by direction (income/expense),
then clusters occurrences by amount within that direction (a single IBAN or
merchant can carry more than one recurring pattern, e.g. a salary payer
that also reimburses expense claims to the same account). Each qualifying
amount cluster is classified for cadence (monthly, four_weekly, yearly)
from the gaps between its occurrence dates and its own amount stability.

Detection runs on the full transaction history each time (single-user
scale); `upsert_recurring_payments` refreshes `suggested` rows in place and
never touches `confirmed` or `dismissed` rows.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import RecurringPayment, RecurringPaymentOccurrence, Transaction
from .merchant import normalize_merchant_name
from .nl_holidays import (
    shift_backward_to_business_day,
    shift_forward_to_business_day,
)

# --- Detection thresholds (named constants, see spec "Recurring-payment
# detection") -----------------------------------------------------------

MIN_OCCURRENCES_MONTHLY = 3
MIN_OCCURRENCES_FOUR_WEEKLY = 3
MIN_OCCURRENCES_YEARLY = 2

MONTHLY_GAP_MIN_DAYS = 26
MONTHLY_GAP_MAX_DAYS = 36
# four_weekly has a tight band (used to actually classify the cadence) and
# a wider band (used to check how many of the remaining, non-outlier gaps
# sit close enough to 28 days to call the cadence steady).
FOUR_WEEKLY_GAP_TIGHT_MIN_DAYS = 27
FOUR_WEEKLY_GAP_TIGHT_MAX_DAYS = 29
FOUR_WEEKLY_GAP_WIDE_MIN_DAYS = 26
FOUR_WEEKLY_GAP_WIDE_MAX_DAYS = 30
FOUR_WEEKLY_QUALIFYING_FRACTION = 0.6
YEARLY_GAP_MIN_DAYS = 350
YEARLY_GAP_MAX_DAYS = 380

# Cadence classification tolerates up to this fraction of gaps being
# outliers: they are dropped (furthest from the median gap first) before
# the median gap and windowed checks are computed. This lets a mostly
# regular series (one skipped or delayed cycle) still classify correctly.
GAP_OUTLIER_FRACTION = 0.25

DAY_OF_MONTH_TOLERANCE = 4
# A monthly call by day-of-month stability only needs this fraction of
# dates within +/-DAY_OF_MONTH_TOLERANCE of the median day, not all of
# them (real data has the odd weekend/holiday-shifted or delayed payment).
DAY_STABLE_QUALIFYING_FRACTION = 0.75

# Fallback monthly rule: when the day-of-month isn't stable enough (e.g. a
# direct debit whose collection day genuinely wanders), a monthly-range gap
# combined with near-identical amounts is still a strong enough signal
# (ANWB-style: fixed amount, wandering collection day).
FIXED_AMOUNT_TOLERANCE = 0.05

AMOUNT_TOLERANCE_FRACTION = 0.15
AMOUNT_QUALIFYING_FRACTION = 0.75
DEFAULT_AMOUNT_TOLERANCE = 0.15
# Amount clustering: within a (group key, direction) series, an amount
# joins the running cluster when within this fraction of the cluster's
# running median; otherwise it starts a new cluster. Same value as
# AMOUNT_TOLERANCE_FRACTION, named separately because it plays a different
# role (clustering occurrences vs. the post-hoc qualifying check on an
# already-formed cluster).
AMOUNT_QUALIFY_TOLERANCE = 0.15

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


def _trimmed_gaps(gaps: Sequence[int]) -> list[int]:
    """Drop up to GAP_OUTLIER_FRACTION of `gaps`, furthest from the median
    first, before cadence checks run on the remainder."""
    if not gaps:
        return list(gaps)
    median = statistics.median(gaps)
    # Floor rounding is deliberate: a fractional allowance (e.g. 3 gaps *
    # 0.25 = 0.75) rounds down to 0, so a short series only gets an outlier
    # dropped once it can clearly afford one, not on a rounded-up technicality.
    n_drop = int(len(gaps) * GAP_OUTLIER_FRACTION)
    if n_drop == 0:
        return list(gaps)
    ordered = sorted(gaps, key=lambda g: abs(g - median))
    return ordered[: len(gaps) - n_drop]


def _day_stable_fraction(dates: Sequence[date], median_day: float) -> float:
    within = [d for d in dates if abs(d.day - median_day) <= DAY_OF_MONTH_TOLERANCE]
    return len(within) / len(dates)


def _amount_fixed_fraction(amounts: Sequence[float]) -> float:
    abs_amounts = [abs(a) for a in amounts]
    median = statistics.median(abs_amounts)
    if median == 0:
        return 0.0
    within = [a for a in abs_amounts if abs(a - median) <= FIXED_AMOUNT_TOLERANCE * median]
    return len(within) / len(abs_amounts)


def detect_cadence(dates: Sequence[date], amounts: Sequence[float] | None = None) -> CadenceResult | None:
    """Classify the cadence of a series of occurrence dates (optionally with
    their amounts, for the monthly fixed-amount fallback).

    See spec "Recurring-payment detection" (cadence rules v2) for the exact
    rules:

    - monthly needs 3+ occurrences with a trimmed median gap of 26-36 days
      AND either the day-of-month is stable (within +/-4) for >=75% of
      dates, OR (fallback) >=75% of amounts are within 5% of the median
      amount.
    - four_weekly needs 3+ occurrences with a trimmed median gap of 27-29
      days and >=60% of the (non-outlier) gaps within 26-30 days, and must
      not already qualify as day-stable monthly.
    - yearly needs 2+ occurrences with a 350-380 day median gap.

    Up to GAP_OUTLIER_FRACTION of gaps are ignored as outliers (dropped,
    furthest from the median first) before any of the above is evaluated.
    """
    if amounts is not None and len(amounts) != len(dates):
        raise ValueError("amounts must be the same length as dates")

    pairs = sorted(zip(dates, amounts) if amounts is not None else zip(dates, [None] * len(dates)))
    ordered = [p[0] for p in pairs]
    ordered_amounts = [p[1] for p in pairs] if amounts is not None else None

    if len(ordered) >= MIN_OCCURRENCES_MONTHLY:
        gaps = _gaps(ordered)
        trimmed = _trimmed_gaps(gaps)
        median_gap = statistics.median(trimmed)

        days_of_month = [d.day for d in ordered]
        median_day = statistics.median(days_of_month)
        day_stable = _day_stable_fraction(ordered, median_day) >= DAY_STABLE_QUALIFYING_FRACTION

        if MONTHLY_GAP_MIN_DAYS <= median_gap <= MONTHLY_GAP_MAX_DAYS and day_stable:
            return CadenceResult(
                cadence="monthly", expected_day=round(median_day), anchor_date=ordered[-1]
            )

        if FOUR_WEEKLY_GAP_TIGHT_MIN_DAYS <= median_gap <= FOUR_WEEKLY_GAP_TIGHT_MAX_DAYS:
            within_wide = [
                g for g in trimmed if FOUR_WEEKLY_GAP_WIDE_MIN_DAYS <= g <= FOUR_WEEKLY_GAP_WIDE_MAX_DAYS
            ]
            if len(within_wide) / len(trimmed) >= FOUR_WEEKLY_QUALIFYING_FRACTION:
                return CadenceResult(
                    cadence="four_weekly", expected_day=None, anchor_date=ordered[-1]
                )

        amount_fixed = (
            ordered_amounts is not None
            and _amount_fixed_fraction(ordered_amounts) >= DAY_STABLE_QUALIFYING_FRACTION
        )
        if MONTHLY_GAP_MIN_DAYS <= median_gap <= MONTHLY_GAP_MAX_DAYS and amount_fixed:
            return CadenceResult(
                cadence="monthly", expected_day=round(median_day), anchor_date=ordered[-1]
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
    don't disqualify the group. Acts as a safety net on top of amount
    clustering, which already groups occurrences by amount."""
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


def _cluster_by_amount(transactions: Sequence[Transaction]) -> list[list[Transaction]]:
    """Greedy amount clustering: process occurrences in ascending order of
    absolute amount, joining the current cluster when within
    AMOUNT_QUALIFY_TOLERANCE of that cluster's running median; otherwise
    starting a new cluster. This is what separates, e.g., a salary cluster
    from an expense-claim-reimbursement cluster sharing the same payer."""
    ordered = sorted(transactions, key=lambda t: abs(t.bedrag))
    clusters: list[list[Transaction]] = []
    for tx in ordered:
        if clusters:
            current = clusters[-1]
            median = statistics.median(abs(t.bedrag) for t in current)
            if median > 0 and abs(abs(tx.bedrag) - median) <= AMOUNT_QUALIFY_TOLERANCE * median:
                current.append(tx)
                continue
        clusters.append([tx])
    return clusters


def _cluster_group_key(base_key: str, direction: str, amount: float) -> str:
    """The stable composite identity for a cluster: base key, direction,
    and the cluster's representative amount rounded to the nearest euro.
    Rounded amount (not an ordinal cluster index) is deliberate: a new
    cluster appearing between two existing ones (e.g. a 60 cluster showing
    up alongside existing 10 and 150 clusters) must not shift the other
    clusters' keys, or upsert would drop and recreate them instead of
    refreshing in place."""
    return f"{base_key}|{direction}|{int(round(abs(amount)))}"


def _build_candidate(
    base_key: str, direction: str, txs: Sequence[Transaction]
) -> RecurringCandidate | None:
    txs_sorted = sorted(txs, key=lambda t: t.datum)
    dates = [t.datum for t in txs_sorted]
    amounts = [t.bedrag for t in txs_sorted]

    cadence_result = detect_cadence(dates, amounts)
    if cadence_result is None:
        return None

    if not amounts_qualify(amounts):
        return None

    counterparty_iban = txs_sorted[0].tegenrekening
    merchant_pattern = "" if counterparty_iban else base_key
    display_name = txs_sorted[0].merchant_name or txs_sorted[0].naam or base_key
    expected_amount = statistics.median(amounts)
    is_income = expected_amount > 0

    occurrences = tuple(
        Occurrence(transaction_id=t.id, amount=t.bedrag, date=t.datum) for t in txs_sorted
    )

    return RecurringCandidate(
        group_key=_cluster_group_key(base_key, direction, expected_amount),
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


def build_candidates(transactions: Iterable[Transaction]) -> list[RecurringCandidate]:
    """Pure detection over an in-memory list of transactions: group by
    counterparty/merchant, split by direction, cluster by amount within
    each direction, then classify cadence per cluster. Excludes internal
    transfers."""
    groups: dict[str, list[Transaction]] = {}
    for tx in transactions:
        if tx.is_internal_transfer:
            continue
        key = _group_key(tx)
        if key is None:
            continue
        groups.setdefault(key, []).append(tx)

    candidates: list[RecurringCandidate] = []
    for base_key, txs in groups.items():
        for direction, direction_txs in (
            ("income", [t for t in txs if t.bedrag > 0]),
            ("expense", [t for t in txs if t.bedrag < 0]),
        ):
            if not direction_txs:
                continue
            clusters = _cluster_by_amount(direction_txs)
            for cluster_txs in clusters:
                if len(cluster_txs) < MIN_OCCURRENCES_YEARLY:
                    continue
                candidate = _build_candidate(base_key, direction, cluster_txs)
                if candidate is not None:
                    candidates.append(candidate)

    return candidates


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
    the pattern temporarily drops out of detection).

    Rows without a persisted `group_key` (created before clustering
    existed, or created directly, e.g. in tests) predate multi-cluster
    detection, so they're matched to a candidate by base key + direction
    alone rather than by amount: there is at most one such legacy row per
    (base key, direction), and it stands in for whichever single candidate
    now occupies that slot, regardless of how much its amount may have
    drifted since it was first detected."""
    existing_rows = db.query(RecurringPayment).all()
    keyed_rows: dict[str, RecurringPayment] = {
        row.group_key: row for row in existing_rows if row.group_key
    }
    current_keys = {candidate.group_key for candidate in candidates}

    deleted_ids: set[int] = set()
    for row in existing_rows:
        if row.group_key and row.status == "suggested" and row.group_key not in current_keys:
            db.delete(row)
            deleted_ids.add(row.id)
    db.flush()

    legacy_rows_by_base_direction: dict[tuple[str, str], list[RecurringPayment]] = {}
    for row in existing_rows:
        if row.group_key or row.id in deleted_ids:
            continue
        base = row.counterparty_iban if row.counterparty_iban else row.merchant_pattern
        direction = "income" if row.is_income else "expense"
        legacy_rows_by_base_direction.setdefault((base, direction), []).append(row)

    claimed_legacy_ids: set[int] = set()

    def resolve_row(candidate: RecurringCandidate) -> RecurringPayment | None:
        row = keyed_rows.get(candidate.group_key)
        if row is not None:
            return row
        base = candidate.counterparty_iban if candidate.counterparty_iban else candidate.merchant_pattern
        direction = "income" if candidate.is_income else "expense"
        unclaimed = [
            r
            for r in legacy_rows_by_base_direction.get((base, direction), [])
            if r.id not in claimed_legacy_ids
        ]
        # Only match unambiguously: if more than one legacy row shares this
        # base key/direction (shouldn't happen in practice, since legacy
        # rows predate multi-cluster detection), don't guess which one this
        # candidate corresponds to.
        if len(unclaimed) == 1:
            claimed_legacy_ids.add(unclaimed[0].id)
            return unclaimed[0]
        return None

    result: list[RecurringPayment] = []
    for candidate in candidates:
        row = resolve_row(candidate)
        if row is not None and row.status != "suggested":
            continue

        if row is None:
            row = RecurringPayment(status="suggested")
            db.add(row)

        row.group_key = candidate.group_key
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

    # Legacy suggested rows not claimed by any candidate this run are stale.
    for rows in legacy_rows_by_base_direction.values():
        for row in rows:
            if row.status == "suggested" and row.id not in claimed_legacy_ids:
                db.delete(row)

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
    """The next occurrence date expected after `payment.anchor_date`, in
    calendar terms (not weekend/holiday-shifted; see `shift_expected_date`
    for the shifted, banking-day version used for display and matching).

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


def shift_expected_date(d: date, cadence: str, is_income: bool) -> date:
    """Shift an expected monthly/yearly date onto the nearest actual
    banking day: income shifts backward (paid early when it would land on
    a weekend/NL holiday), expenses shift forward (collected the next
    banking day). four_weekly dates are never shifted; their date is
    already a fixed step from `anchor_date`, not tied to a calendar day.

    Single source of truth shared by the calendar/advisor
    (`app.services.cashflow_advisor`) and import-time matching
    (`match_new_transactions`), so a payment's expected date always lands
    on the same real-world day everywhere it's used."""
    if cadence == "four_weekly":
        return d
    return shift_backward_to_business_day(d) if is_income else shift_forward_to_business_day(d)


def find_salary_payment_id(db: Session) -> int | None:
    """The confirmed income recurring payment most likely to be the salary:
    most occurrences wins; ties broken by the latest occurrence date, then
    by lowest id, so the pick is deterministic. Shared by the cashflow
    router (periods/calendar) and the cashflow advisor so both agree on
    which payment is "the" salary."""
    row = db.execute(
        select(
            RecurringPaymentOccurrence.recurring_payment_id,
            func.count(RecurringPaymentOccurrence.id).label("occurrence_count"),
            func.max(RecurringPaymentOccurrence.date).label("latest_date"),
        )
        .join(RecurringPayment, RecurringPayment.id == RecurringPaymentOccurrence.recurring_payment_id)
        .where(RecurringPayment.status == "confirmed", RecurringPayment.is_income.is_(True))
        .group_by(RecurringPaymentOccurrence.recurring_payment_id)
        .order_by(
            func.count(RecurringPaymentOccurrence.id).desc(),
            func.max(RecurringPaymentOccurrence.date).desc(),
            RecurringPaymentOccurrence.recurring_payment_id.asc(),
        )
        .limit(1)
    ).first()
    return row[0] if row else None


def backfill_occurrences(db: Session, payment: RecurringPayment) -> None:
    """Rebuild `payment`'s occurrences from the full transaction history:
    same base group key (counterparty IBAN or normalized merchant name),
    same direction (income/expense), and amount within
    AMOUNT_QUALIFY_TOLERANCE of `payment.expected_amount` (the same
    tolerance used to form the amount cluster in the first place). Called
    on confirm so a just-confirmed pattern has its complete history
    recorded, independent of whatever the last detector run happened to
    populate."""
    base_key = payment.counterparty_iban if payment.counterparty_iban else payment.merchant_pattern
    median = abs(payment.expected_amount)

    transactions = db.query(Transaction).all()
    matches = [
        tx
        for tx in transactions
        if not tx.is_internal_transfer
        and _group_key(tx) == base_key
        and (tx.bedrag > 0) == payment.is_income
        and (median == 0 or abs(abs(tx.bedrag) - median) <= AMOUNT_QUALIFY_TOLERANCE * median)
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
    base group key and direction, date within
    +/-DATE_MATCH_WINDOW_DAYS of the shift-aware expected date (via
    `shift_expected_date`, same as the calendar/advisor use), amount within
    MATCH_WIDE_BAND of expected_amount. A base key can have more than one
    confirmed pattern (e.g. a salary cluster and a claims-reimbursement
    cluster sharing an IBAN); the first confirmed row for that base key
    whose direction/date/amount checks all pass is used. A match appends an
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

    by_base_key: dict[str, list[RecurringPayment]] = {}
    for row in confirmed:
        base = row.counterparty_iban if row.counterparty_iban else row.merchant_pattern
        by_base_key.setdefault(base, []).append(row)

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

        row = None
        for candidate_row in by_base_key.get(key, []):
            if (tx.bedrag > 0) != candidate_row.is_income:
                continue
            expected_date = next_expected_date(candidate_row)
            if expected_date is None:
                continue
            shifted_expected_date = shift_expected_date(
                expected_date, candidate_row.cadence, candidate_row.is_income
            )
            if abs((tx.datum - shifted_expected_date).days) > DATE_MATCH_WINDOW_DAYS:
                continue
            if amount_deviates(tx.bedrag, candidate_row.expected_amount, MATCH_WIDE_BAND):
                continue
            row = candidate_row
            break
        if row is None:
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
