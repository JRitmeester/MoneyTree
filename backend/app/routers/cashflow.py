from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import RecurringPayment, RecurringPaymentOccurrence
from ..schemas import CashflowPeriodOut

router = APIRouter(prefix="/api/cashflow", tags=["cashflow"], dependencies=[Depends(require_auth)])


def _format_period_date(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


@router.get("/periods", response_model=list[CashflowPeriodOut])
def get_periods(count: int = Query(6, ge=1, le=24), db: Session = Depends(get_db)):
    """Salary-anchored pay periods, newest first.

    The salary is the confirmed income recurring payment with the most
    occurrences. Each period runs from one salary occurrence date
    (inclusive) to the day before the next; the newest period is open,
    running from its occurrence date through today. Returns [] when there
    is no confirmed income recurring payment."""
    salary_row = db.execute(
        select(
            RecurringPaymentOccurrence.recurring_payment_id,
            func.count(RecurringPaymentOccurrence.id).label("occurrence_count"),
        )
        .join(
            RecurringPayment,
            RecurringPayment.id == RecurringPaymentOccurrence.recurring_payment_id,
        )
        .where(RecurringPayment.status == "confirmed", RecurringPayment.is_income.is_(True))
        .group_by(RecurringPaymentOccurrence.recurring_payment_id)
        .order_by(func.count(RecurringPaymentOccurrence.id).desc())
        .limit(1)
    ).first()

    if salary_row is None:
        return []

    payment_id = salary_row[0]
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
