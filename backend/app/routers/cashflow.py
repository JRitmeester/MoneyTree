import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import AppSetting, RecurringPayment, RecurringPaymentOccurrence
from ..schemas import (
    CashflowAdviceOut,
    CashflowCalendarDayOut,
    CashflowCalendarItemOut,
    CashflowCalendarOut,
    CashflowPeriodOut,
    CashflowReturnTransferOut,
    CashflowSettingsOut,
    CashflowSettingsUpdate,
)
from ..services.cashflow_advisor import (
    DEFAULT_BUFFER_PCT,
    compute_advice,
    project_calendar_month,
)
from ..services.recurring_detector import find_salary_payment_id

router = APIRouter(prefix="/api/cashflow", tags=["cashflow"], dependencies=[Depends(require_auth)])

BUFFER_PCT_KEY = "buffer_pct"
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def get_buffer_pct(db: Session) -> float:
    row = db.get(AppSetting, BUFFER_PCT_KEY)
    return float(row.value) if row else DEFAULT_BUFFER_PCT


def _format_period_date(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


@router.get("/periods", response_model=list[CashflowPeriodOut])
def get_periods(count: int = Query(6, ge=1, le=24), db: Session = Depends(get_db)):
    """Salary-anchored pay periods, newest first.

    The salary is the confirmed income recurring payment with the most
    occurrences (see `find_salary_payment_id`). Each period runs from one
    salary occurrence date (inclusive) to the day before the next; the
    newest period is open, running from its occurrence date through today.
    Returns [] when there is no confirmed income recurring payment."""
    payment_id = find_salary_payment_id(db)
    if payment_id is None:
        return []

    occurrence_dates = db.execute(
        select(RecurringPaymentOccurrence.date)
        .where(RecurringPaymentOccurrence.recurring_payment_id == payment_id)
        .order_by(RecurringPaymentOccurrence.date)
    ).scalars().all()

    if not occurrence_dates:
        return []

    today = date.today()
    periods: list[CashflowPeriodOut] = []
    for i, start in enumerate(occurrence_dates):
        if i + 1 < len(occurrence_dates):
            end = occurrence_dates[i + 1] - timedelta(days=1)
            label = f"{_format_period_date(start)} - {_format_period_date(end)}"
        else:
            end = today
            label = "Current"
        periods.append(CashflowPeriodOut(start_date=start, end_date=end, label=label))

    periods.reverse()
    return periods[:count]


@router.get("/calendar", response_model=CashflowCalendarOut)
def get_calendar(month: str = Query(...), db: Session = Depends(get_db)):
    """Per-day expected debits/credits for `month` (YYYY-MM), projected from
    confirmed recurring payments. See spec "Cash-flow calendar and transfer
    advisor"."""
    if not _MONTH_RE.match(month):
        raise HTTPException(status_code=400, detail="month must be in YYYY-MM format")
    year, month_num = (int(part) for part in month.split("-"))
    if not 1 <= month_num <= 12:
        raise HTTPException(status_code=400, detail="month must be in YYYY-MM format")

    payments = db.query(RecurringPayment).filter_by(status="confirmed").all()
    salary_payment_id = find_salary_payment_id(db)
    items = project_calendar_month(payments, year, month_num, salary_payment_id)

    days: dict[date, list[CashflowCalendarItemOut]] = {}
    for item in items:
        days.setdefault(item.date, []).append(
            CashflowCalendarItemOut(
                recurring_payment_id=item.recurring_payment_id,
                name=item.name,
                amount=item.amount,
                is_income=item.is_income,
                is_salary=item.is_salary,
            )
        )

    return CashflowCalendarOut(
        month=month,
        days=[
            CashflowCalendarDayOut(date=d, items=day_items)
            for d, day_items in sorted(days.items())
        ],
    )


@router.get("/advice", response_model=CashflowAdviceOut)
def get_advice(db: Session = Depends(get_db)):
    """Sweep amount, at most two return-transfer recommendations, and
    warnings, computed on read from confirmed recurring payments. See spec
    "Cash-flow calendar and transfer advisor"."""
    buffer_pct = get_buffer_pct(db)
    advice = compute_advice(db, buffer_pct)
    return CashflowAdviceOut(
        salary_confirmed=advice.salary_confirmed,
        message=advice.message,
        payday=advice.payday,
        next_payday=advice.next_payday,
        sweep_amount=advice.sweep_amount,
        keep_in_checking=advice.keep_in_checking,
        standing_buffer=advice.standing_buffer,
        buffer_pct=advice.buffer_pct,
        return_transfers=[
            CashflowReturnTransferOut(
                date=t.date, amount=t.amount, cadence=t.cadence, covers=t.covers
            )
            for t in advice.return_transfers
        ],
        warnings=advice.warnings,
    )


@router.get("/settings", response_model=CashflowSettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return CashflowSettingsOut(buffer_pct=get_buffer_pct(db))


@router.put("/settings", response_model=CashflowSettingsOut)
def update_settings(data: CashflowSettingsUpdate, db: Session = Depends(get_db)):
    row = db.get(AppSetting, BUFFER_PCT_KEY)
    if row is None:
        row = AppSetting(key=BUFFER_PCT_KEY, value=str(data.buffer_pct))
        db.add(row)
    else:
        row.value = str(data.buffer_pct)
    db.commit()
    return CashflowSettingsOut(buffer_pct=data.buffer_pct)
