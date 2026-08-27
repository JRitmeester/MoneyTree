from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import RecurringPayment, RecurringPaymentOccurrence, Transaction
from ..schemas import (
    RecurringNoticeOut,
    RecurringPaymentConfirm,
    RecurringPaymentOccurrenceOut,
    RecurringPaymentOut,
    RecurringPaymentUpdate,
    RescanResult,
)
from ..services.recurring_detector import (
    backfill_occurrences,
    compute_notices,
    detect_recurring_payments,
    next_expected_date,
    upsert_recurring_payments,
)

router = APIRouter(prefix="/api/recurring", tags=["recurring"], dependencies=[Depends(require_auth)])


def _to_out(
    payment: RecurringPayment, occurrence_count: int = 0, last_seen=None
) -> RecurringPaymentOut:
    out = RecurringPaymentOut.model_validate(payment)
    if payment.status == "confirmed":
        out.next_expected = next_expected_date(payment)
    out.occurrence_count = occurrence_count
    out.last_seen = last_seen
    return out


def _aggregate_for(db: Session, payment_id: int) -> tuple[int, object | None]:
    """Single-row COUNT/MAX(date) aggregate for one payment's occurrences."""
    row = db.execute(
        select(
            func.count(RecurringPaymentOccurrence.id),
            func.max(RecurringPaymentOccurrence.date),
        ).where(RecurringPaymentOccurrence.recurring_payment_id == payment_id)
    ).one()
    return row[0] or 0, row[1]


@router.get("", response_model=list[RecurringPaymentOut])
def list_recurring(
    status: Literal["suggested", "confirmed", "dismissed"] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = select(RecurringPayment)
    if status is not None:
        query = query.where(RecurringPayment.status == status)
    payments = db.execute(query.order_by(RecurringPayment.id)).scalars().all()

    # One grouped aggregate query for all payments' occurrence counts/last-seen
    # dates, instead of an N+1 lookup per payment.
    aggregates: dict[int, tuple[int, object | None]] = {}
    if payments:
        agg_rows = db.execute(
            select(
                RecurringPaymentOccurrence.recurring_payment_id,
                func.count(RecurringPaymentOccurrence.id),
                func.max(RecurringPaymentOccurrence.date),
            )
            .where(
                RecurringPaymentOccurrence.recurring_payment_id.in_(
                    [p.id for p in payments]
                )
            )
            .group_by(RecurringPaymentOccurrence.recurring_payment_id)
        ).all()
        aggregates = {row[0]: (row[1], row[2]) for row in agg_rows}

    return [
        _to_out(p, *aggregates.get(p.id, (0, None)))
        for p in payments
    ]


@router.get("/notices", response_model=list[RecurringNoticeOut])
def list_notices(db: Session = Depends(get_db)):
    return compute_notices(db)


@router.post("/rescan", response_model=RescanResult)
def rescan(db: Session = Depends(get_db)):
    candidates = detect_recurring_payments(db)
    upsert_recurring_payments(db, candidates)
    db.commit()

    counts = {"suggested": 0, "confirmed": 0, "dismissed": 0}
    rows = db.execute(select(RecurringPayment)).scalars().all()
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return RescanResult(**counts)


@router.get("/{payment_id}/occurrences", response_model=list[RecurringPaymentOccurrenceOut])
def list_occurrences(payment_id: int, db: Session = Depends(get_db)):
    payment = db.get(RecurringPayment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Recurring payment not found")
    occurrences = db.execute(
        select(RecurringPaymentOccurrence)
        .where(RecurringPaymentOccurrence.recurring_payment_id == payment_id)
        .order_by(RecurringPaymentOccurrence.date)
    ).scalars().all()
    return occurrences


@router.post("/{payment_id}/confirm", response_model=RecurringPaymentOut)
def confirm_recurring(payment_id: int, data: RecurringPaymentConfirm, db: Session = Depends(get_db)):
    payment = db.get(RecurringPayment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Recurring payment not found")
    if payment.status == "dismissed":
        raise HTTPException(status_code=409, detail="Cannot confirm a dismissed pattern")

    if data.name is not None:
        payment.name = data.name
    if data.category_id is not None:
        payment.category_id = data.category_id

    payment.status = "confirmed"
    db.flush()
    backfill_occurrences(db, payment)
    db.commit()
    db.refresh(payment)
    count, last_seen = _aggregate_for(db, payment.id)
    return _to_out(payment, count, last_seen)


@router.post("/{payment_id}/dismiss", response_model=RecurringPaymentOut)
def dismiss_recurring(payment_id: int, db: Session = Depends(get_db)):
    payment = db.get(RecurringPayment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Recurring payment not found")
    payment.status = "dismissed"
    db.commit()
    db.refresh(payment)
    count, last_seen = _aggregate_for(db, payment.id)
    return _to_out(payment, count, last_seen)


@router.patch("/{payment_id}", response_model=RecurringPaymentOut)
def update_recurring(payment_id: int, data: RecurringPaymentUpdate, db: Session = Depends(get_db)):
    payment = db.get(RecurringPayment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Recurring payment not found")

    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(payment, key, value)

    db.commit()
    db.refresh(payment)
    count, last_seen = _aggregate_for(db, payment.id)
    return _to_out(payment, count, last_seen)
