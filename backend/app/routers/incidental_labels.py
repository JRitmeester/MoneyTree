from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import IncidentalLabel, Transaction
from ..schemas import IncidentalLabelCreate, IncidentalLabelOut, IncidentalLabelSummary

router = APIRouter(
    prefix="/api/incidental-labels",
    tags=["incidental-labels"],
    dependencies=[Depends(require_auth)],
)


@router.get("", response_model=list[IncidentalLabelSummary])
def list_labels(db: Session = Depends(get_db)):
    """All labels with spending totals: total is net money out (expenses
    minus refunds), so a partially refunded holiday shows what it truly cost."""
    rows = db.execute(
        select(
            IncidentalLabel,
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.bedrag), 0.0),
            func.min(Transaction.datum),
            func.max(Transaction.datum),
        )
        .outerjoin(Transaction, Transaction.incidental_label_id == IncidentalLabel.id)
        .group_by(IncidentalLabel.id)
        .order_by(IncidentalLabel.name)
    ).all()

    return [
        IncidentalLabelSummary(
            id=label.id,
            name=label.name,
            total=round(-total, 2),
            count=count,
            date_from=date_from,
            date_to=date_to,
        )
        for label, count, total, date_from, date_to in rows
    ]


@router.post("", response_model=IncidentalLabelOut)
def create_label(data: IncidentalLabelCreate, db: Session = Depends(get_db)):
    existing = db.execute(
        select(IncidentalLabel).where(IncidentalLabel.name == data.name)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="A label with this name already exists")

    label = IncidentalLabel(name=data.name)
    db.add(label)
    db.commit()
    db.refresh(label)
    return label


@router.patch("/{label_id}", response_model=IncidentalLabelOut)
def rename_label(label_id: int, data: IncidentalLabelCreate, db: Session = Depends(get_db)):
    label = db.get(IncidentalLabel, label_id)
    if not label:
        raise HTTPException(status_code=404, detail="Label not found")

    duplicate = db.execute(
        select(IncidentalLabel).where(
            IncidentalLabel.name == data.name, IncidentalLabel.id != label_id
        )
    ).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="A label with this name already exists")

    label.name = data.name
    db.commit()
    db.refresh(label)
    return label


@router.delete("/{label_id}")
def delete_label(label_id: int, db: Session = Depends(get_db)):
    """Deleting a label detaches its transactions but keeps them incidental."""
    label = db.get(IncidentalLabel, label_id)
    if not label:
        raise HTTPException(status_code=404, detail="Label not found")

    linked = db.execute(
        select(Transaction).where(Transaction.incidental_label_id == label_id)
    ).scalars().all()
    for tx in linked:
        tx.incidental_label_id = None
    db.delete(label)
    db.commit()
    return {"ok": True}
