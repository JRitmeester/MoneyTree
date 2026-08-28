"""Cash-flow calendar projection and transfer advisor.

See docs/superpowers/specs/2026-08-27-financial-insights-design.md, section
"Cash-flow calendar and transfer advisor". Two responsibilities live here:

- Calendar projection: place confirmed recurring payments onto specific
  calendar dates for a given month, shifting monthly/yearly items off
  weekends onto the next business day (four-weekly items are not shifted;
  their date is a fixed step from `anchor_date`).
- Transfer advice: on-read computation of a payday sweep amount, at most
  two return-transfer recommendations, and a warnings list. Nothing except
  `buffer_pct` is persisted; the rest is recomputed from confirmed
  recurring payments every time.
"""
from __future__ import annotations

import calendar as _calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..models import RecurringPayment
from .recurring_detector import (
    compute_notices,
    find_salary_payment_id,
    next_expected_date,
    shift_expected_date,
)

DEFAULT_BUFFER_PCT = 10.0

# Debits within this many days before payday raise a "lands right before
# payday" warning: the sweep that just happened won't have covered them.
PRE_PAYDAY_WARNING_DAYS = 7

# Yearly items with a next-expected date within this many days are called
# out explicitly, since a single large yearly hit can blindside a sweep
# sized around the usual monthly pattern.
YEARLY_DUE_SOON_DAYS = 30

# A debit more than this many days after its cluster's first (earliest)
# debit starts a new cluster for return-transfer purposes. Measured from
# the cluster's start (not the previous debit) so a chain of closely spaced
# debits can't drag in a distant one transitively.
CLUSTER_MAX_SPAN_DAYS = 6

# At most this many return-transfer recommendations are produced; smaller
# clusters beyond this count are still covered by the sweep, just without a
# dedicated transfer.
MAX_RETURN_TRANSFERS = 2

# Four-weekly debits at or below this absolute amount are folded into the
# standing buffer instead of getting their own dedicated four-weekly
# transfer; above it, the item gets its own return-transfer entry.
FOUR_WEEKLY_FOLD_THRESHOLD = 50.0

# A return transfer must arrive at least this many business days before the
# earliest debit it covers.
TRANSFER_LEAD_BUSINESS_DAYS = 2


def _is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def next_business_day(d: date) -> date:
    while _is_weekend(d):
        d += timedelta(days=1)
    return d


def business_days_before(d: date, count: int) -> date:
    """Step backward `count` business days from `d` (exclusive of `d`)."""
    result = d
    steps = 0
    while steps < count:
        result -= timedelta(days=1)
        if not _is_weekend(result):
            steps += 1
    return result


def _add_months(base: date, months: int, day: int) -> date:
    month_index = base.month - 1 + months
    year = base.year + month_index // 12
    month = month_index % 12 + 1
    days_in_month = _calendar.monthrange(year, month)[1]
    return date(year, month, min(day, days_in_month))


def _months_spanning(start: date, end: date) -> list[tuple[int, int]]:
    """Calendar (year, month) pairs overlapping [start, end)."""
    months: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while date(y, m, 1) < end:
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _monthly_date_in_month(
    day: int, year: int, month: int, *, shift_weekend: bool, is_income: bool = False
) -> date:
    days_in_month = _calendar.monthrange(year, month)[1]
    d = date(year, month, min(day, days_in_month))
    return shift_expected_date(d, "monthly", is_income) if shift_weekend else d


def _four_weekly_dates_between(anchor: date, start: date, end: date) -> list[date]:
    """All four-weekly occurrence dates (stepping 28 days from `anchor`)
    landing in [start, end)."""
    if anchor >= start:
        d = anchor
        while d >= start:
            d -= timedelta(days=28)
    else:
        d = anchor
        while d < start:
            d += timedelta(days=28)
        # d is now the first occurrence >= start; back off one step so the
        # loop below re-adds it as the first result.
        d -= timedelta(days=28)

    results = []
    d += timedelta(days=28)
    while d < end:
        results.append(d)
        d += timedelta(days=28)
    return results


def occurrences_in_range(
    payment: RecurringPayment, start: date, end: date, *, shift_weekend: bool = False
) -> list[date]:
    """All of `payment`'s projected occurrence dates in [start, end)."""
    if payment.cadence == "four_weekly":
        return _four_weekly_dates_between(payment.anchor_date, start, end)

    if payment.expected_day is None:
        return []

    results = []
    for year, month in _months_spanning(start, end):
        if payment.cadence == "yearly" and payment.anchor_date.month != month:
            continue
        d = _monthly_date_in_month(
            payment.expected_day, year, month, shift_weekend=shift_weekend, is_income=payment.is_income
        )
        if start <= d < end:
            results.append(d)
    return results


# --- Calendar -------------------------------------------------------------


@dataclass(frozen=True)
class CalendarItem:
    date: date
    recurring_payment_id: int
    name: str
    amount: float
    is_income: bool
    is_salary: bool


def project_calendar_month(
    payments: list[RecurringPayment], year: int, month: int, salary_payment_id: int | None
) -> list[CalendarItem]:
    """Project all confirmed `payments` onto dates within the given month."""
    start = date(year, month, 1)
    days_in_month = _calendar.monthrange(year, month)[1]
    end = date(year, month, days_in_month) + timedelta(days=1)

    items: list[CalendarItem] = []
    for payment in payments:
        for d in occurrences_in_range(payment, start, end, shift_weekend=True):
            items.append(
                CalendarItem(
                    date=d,
                    recurring_payment_id=payment.id,
                    name=payment.name,
                    amount=payment.expected_amount,
                    is_income=payment.is_income,
                    is_salary=payment.id == salary_payment_id,
                )
            )
    items.sort(key=lambda i: i.date)
    return items


# --- Advisor ----------------------------------------------------------------


@dataclass(frozen=True)
class ReturnTransfer:
    date: date
    amount: float
    cadence: str
    covers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SweepItem:
    """One expected debit in the sweep window, exposed so the UI can show
    the full calculation behind the sweep amount."""

    name: str
    date: date
    amount: float  # absolute
    cadence: str
    kept_in_checking: bool


@dataclass(frozen=True)
class Advice:
    salary_confirmed: bool
    message: str | None = None
    payday: date | None = None
    next_payday: date | None = None
    sweep_amount: float | None = None
    keep_in_checking: float = 0.0
    standing_buffer: float = 0.0
    buffer_pct: float = DEFAULT_BUFFER_PCT
    covered_total: float = 0.0
    buffer_amount: float = 0.0
    sweep_items: list[SweepItem] = field(default_factory=list)
    return_transfers: list[ReturnTransfer] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _find_salary_payment(db: Session) -> RecurringPayment | None:
    """The confirmed income recurring payment most likely to be the salary.
    See `find_salary_payment_id` for the tie-break rules; shared with the
    calendar/periods endpoints so both agree on which payment is salary."""
    payment_id = find_salary_payment_id(db)
    if payment_id is None:
        return None
    return db.get(RecurringPayment, payment_id)


def _next_payday_after(payment: RecurringPayment, after: date) -> date:
    if payment.cadence == "four_weekly":
        return after + timedelta(days=28)
    months = 12 if payment.cadence == "yearly" else 1
    return _add_months(after, months, payment.expected_day)


def _shift_for_cadence(d: date, cadence: str, is_income: bool) -> date:
    """Shift a monthly/yearly date onto the nearest actual banking day
    (income backward, expenses forward); four-weekly dates are never
    shifted. Mirrors `occurrences_in_range`'s `shift_weekend` handling so
    the advisor's payday always matches what the calendar view shows for
    the same recurring payment."""
    return shift_expected_date(d, cadence, is_income)


@dataclass(frozen=True)
class _Debit:
    date: date
    amount: float  # absolute
    name: str
    cadence: str


def _cluster_debits(debits: list[_Debit]) -> list[list[_Debit]]:
    if not debits:
        return []
    ordered = sorted(debits, key=lambda d: d.date)
    clusters: list[list[_Debit]] = [[ordered[0]]]
    for cur in ordered[1:]:
        cluster_start = clusters[-1][0].date
        if (cur.date - cluster_start).days > CLUSTER_MAX_SPAN_DAYS:
            clusters.append([cur])
        else:
            clusters[-1].append(cur)
    return clusters


def compute_advice(db: Session, buffer_pct: float, today: date | None = None) -> Advice:
    today = today or date.today()
    salary = _find_salary_payment(db)
    if salary is None:
        return Advice(
            salary_confirmed=False,
            message="Confirm your salary as recurring income first",
            buffer_pct=buffer_pct,
        )

    raw_payday = next_expected_date(salary)
    if raw_payday is None:
        return Advice(
            salary_confirmed=False,
            message="Confirm your salary as recurring income first",
            buffer_pct=buffer_pct,
        )

    warnings: list[str] = []

    # Stale payday: if the salary's next expected date has already passed
    # (the detector hasn't matched it against a real transaction yet), roll
    # forward by cadence until it's not in the past, and say so, rather than
    # silently computing a window that already closed.
    original_raw_payday = raw_payday
    while raw_payday < today:
        raw_payday = _next_payday_after(salary, raw_payday)
    if raw_payday != original_raw_payday:
        warnings.append(
            f"Salary expected on {original_raw_payday.isoformat()} has not been seen yet"
        )

    raw_next_payday = _next_payday_after(salary, raw_payday)

    # Weekend/holiday-shifted, matching the calendar view: the sweep happens
    # on the actual banking day the salary lands (income shifts backward),
    # not the raw expected_day.
    payday = _shift_for_cadence(raw_payday, salary.cadence, salary.is_income)
    next_payday = _shift_for_cadence(raw_next_payday, salary.cadence, salary.is_income)

    debit_payments = (
        db.query(RecurringPayment)
        .filter_by(status="confirmed", is_income=False)
        .all()
    )

    # Debits swept for by the upcoming payday (all due before next payday),
    # projected with the same weekend shift as the calendar view.
    window_debits: list[_Debit] = []
    standing_buffer_total = 0.0
    monthly_yearly_debits: list[_Debit] = []
    four_weekly_dedicated: dict[int, list[_Debit]] = {}
    for payment in debit_payments:
        for d in occurrences_in_range(payment, payday, next_payday, shift_weekend=True):
            debit = _Debit(date=d, amount=abs(payment.expected_amount), name=payment.name, cadence=payment.cadence)
            window_debits.append(debit)
            if payment.cadence == "four_weekly":
                if abs(payment.expected_amount) <= FOUR_WEEKLY_FOLD_THRESHOLD:
                    # Folded into the standing buffer: still swept for (it's
                    # part of sweep_total below), just not worth a dedicated
                    # transfer of its own.
                    standing_buffer_total += abs(payment.expected_amount)
                else:
                    four_weekly_dedicated.setdefault(payment.id, []).append(debit)
            else:
                monthly_yearly_debits.append(debit)

    sweep_total = sum(d.amount for d in window_debits)

    # Candidate clusters: span-based groups of monthly/yearly debits, plus
    # one dedicated candidate per above-threshold four-weekly payment
    # (whichever wins between a matching four-weekly transfer and the
    # standing buffer is decided by the fold threshold above; a payment
    # that clears it always gets its own candidate here).
    candidate_clusters = _cluster_debits(monthly_yearly_debits)
    candidate_clusters.extend(four_weekly_dedicated.values())
    candidate_clusters.sort(key=lambda c: sum(d.amount for d in c), reverse=True)
    chosen = candidate_clusters[:MAX_RETURN_TRANSFERS]

    return_transfers: list[ReturnTransfer] = []
    keep_in_checking_total = 0.0
    kept_debit_ids: set[int] = set()
    for cluster in chosen:
        earliest = min(d.date for d in cluster)
        total = sum(d.amount for d in cluster)
        ideal_date = business_days_before(earliest, TRANSFER_LEAD_BUSINESS_DAYS)
        if ideal_date >= payday:
            # A transfer scheduled on `ideal_date` (on or after payday)
            # still arrives the required lead time before the earliest
            # debit it covers.
            cadence = "four_weekly" if all(d.cadence == "four_weekly" for d in cluster) else "monthly"
            return_transfers.append(
                ReturnTransfer(
                    date=max(payday, ideal_date),
                    amount=round(total, 2),
                    cadence=cadence,
                    covers=[d.name for d in cluster],
                )
            )
        else:
            # Even a transfer sent the moment the sweep happens (payday)
            # can't arrive the required lead time before the earliest debit:
            # don't move this money out at all, keep it in checking instead.
            keep_in_checking_total += total
            sweep_total -= total
            kept_debit_ids.update(id(d) for d in cluster)
    return_transfers.sort(key=lambda t: t.date)

    covered_total = round(sweep_total, 2)
    sweep_amount = round(sweep_total * (1 + buffer_pct / 100), 2)
    # Derived as a difference so covered_total + buffer_amount always equals
    # the displayed sweep_amount exactly, independent of rounding.
    buffer_amount = round(sweep_amount - covered_total, 2)

    sweep_items = [
        SweepItem(
            name=d.name,
            date=d.date,
            amount=round(d.amount, 2),
            cadence=d.cadence,
            kept_in_checking=id(d) in kept_debit_ids,
        )
        for d in sorted(window_debits, key=lambda d: d.date)
    ]

    # Pre-payday debits: land in the days just before this payday, so the
    # previous sweep won't have covered them.
    pre_payday_start = payday - timedelta(days=PRE_PAYDAY_WARNING_DAYS)
    for payment in debit_payments:
        for d in occurrences_in_range(payment, pre_payday_start, payday, shift_weekend=True):
            days_before = (payday - d).days
            warnings.append(
                f"{payment.name} is due on {d.isoformat()}, {days_before} day(s) before payday "
                f"on {payday.isoformat()}"
            )

    # Yearly items due soon.
    for payment in debit_payments:
        if payment.cadence != "yearly":
            continue
        expected = next_expected_date(payment)
        if expected is not None:
            expected = shift_expected_date(expected, payment.cadence, payment.is_income)
        if expected is not None and 0 <= (expected - today).days <= YEARLY_DUE_SOON_DAYS:
            warnings.append(f"{payment.name} (yearly) is due on {expected.isoformat()}")

    for notice in compute_notices(db, today=today):
        if notice["type"] == "amount_changed":
            warnings.append(f"{notice['name']}: {notice['detail']}")

    return Advice(
        salary_confirmed=True,
        payday=payday,
        next_payday=next_payday,
        sweep_amount=sweep_amount,
        keep_in_checking=round(keep_in_checking_total, 2),
        standing_buffer=round(standing_buffer_total, 2),
        buffer_pct=buffer_pct,
        covered_total=covered_total,
        buffer_amount=buffer_amount,
        sweep_items=sweep_items,
        return_transfers=return_transfers,
        warnings=warnings,
    )
