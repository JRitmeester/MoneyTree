from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import Category, CategoryMapping, Receipt, Transaction

router = APIRouter(prefix="/api/uncategorized", tags=["uncategorized"], dependencies=[Depends(require_auth)])


class UncategorizedGroup(BaseModel):
    bank_category: str
    count: int
    total: float  # absolute value (positive)
    has_mapping: bool


class BulkCategorizeRequest(BaseModel):
    bank_category: str
    category_id: int
    save_mapping: bool = True


def _uncategorized_query():
    """Expense transactions with no category_id and no receipt."""
    return (
        select(Transaction)
        .where(Transaction.bedrag < 0)
        .where(Transaction.category_id.is_(None))
        .where(
            ~select(Receipt.id)
            .where(Receipt.transaction_id == Transaction.id)
            .exists()
        )
    )


@router.get("", response_model=list[UncategorizedGroup])
def list_uncategorized(db: Session = Depends(get_db)):
    """Return expense transactions with no category, grouped by bank category string."""
    rows = db.execute(_uncategorized_query()).scalars().all()

    groups: dict[str, dict] = {}
    for tx in rows:
        key = tx.categorie or "Unknown"
        if key not in groups:
            groups[key] = {"count": 0, "total": 0.0}
        groups[key]["count"] += 1
        groups[key]["total"] += abs(tx.bedrag)

    # Check which bank categories already have a mapping
    mapped = set(
        db.execute(select(CategoryMapping.bank_category)).scalars().all()
    )

    result = [
        UncategorizedGroup(
            bank_category=key,
            count=data["count"],
            total=round(data["total"], 2),
            has_mapping=key in mapped,
        )
        for key, data in groups.items()
    ]
    result.sort(key=lambda x: x.total, reverse=True)
    return result


@router.post("/bulk-categorize")
def bulk_categorize(data: BulkCategorizeRequest, db: Session = Depends(get_db)):
    """Assign a category to all uncategorized transactions with a given bank category."""
    cat = db.get(Category, data.category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    rows = db.execute(
        _uncategorized_query().where(Transaction.categorie == data.bank_category)
    ).scalars().all()

    for tx in rows:
        tx.category_id = data.category_id

    if data.save_mapping:
        existing = db.execute(
            select(CategoryMapping).where(CategoryMapping.bank_category == data.bank_category)
        ).scalar_one_or_none()
        if existing:
            existing.category_id = data.category_id
        else:
            db.add(CategoryMapping(bank_category=data.bank_category, category_id=data.category_id))

    db.commit()
    return {"updated": len(rows)}
