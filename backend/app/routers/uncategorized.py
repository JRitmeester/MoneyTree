from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import Category, CategoryMapping, Receipt, Transaction

router = APIRouter(prefix="/api/uncategorized", tags=["uncategorized"], dependencies=[Depends(require_auth)])


class UncategorizedTransaction(BaseModel):
    id: int
    datum: date
    bedrag: float
    merchant_name: str | None
    naam: str | None
    omschrijving: str


class UncategorizedGroup(BaseModel):
    bank_category: str
    count: int
    total: float  # absolute value (positive)
    has_mapping: bool
    transactions: list[UncategorizedTransaction]


class CategorizeSelectedRequest(BaseModel):
    transaction_ids: list[int]
    category_id: int


class BulkCategorizeRequest(BaseModel):
    bank_category: str
    category_id: int
    save_mapping: bool = True


def _uncategorized_query():
    """Transactions (expenses and income) with no category_id and no receipt."""
    return (
        select(Transaction)
        .where(Transaction.category_id.is_(None))
        .where(
            ~select(Receipt.id)
            .where(Receipt.transaction_id == Transaction.id)
            .exists()
        )
    )


@router.get("", response_model=list[UncategorizedGroup])
def list_uncategorized(db: Session = Depends(get_db)):
    """Return transactions with no category, grouped by bank category string."""
    rows = db.execute(_uncategorized_query()).scalars().all()

    groups: dict[str, list] = {}
    for tx in rows:
        key = tx.categorie or "Unknown"
        if key not in groups:
            groups[key] = []
        groups[key].append(tx)

    # Check which bank categories already have a mapping
    mapped = set(
        db.execute(select(CategoryMapping.bank_category)).scalars().all()
    )

    result = []
    for key, txs in groups.items():
        total = round(sum(abs(tx.bedrag) for tx in txs), 2)
        sorted_txs = sorted(txs, key=lambda t: t.datum, reverse=True)
        result.append(UncategorizedGroup(
            bank_category=key,
            count=len(txs),
            total=total,
            has_mapping=key in mapped,
            transactions=[
                UncategorizedTransaction(
                    id=tx.id,
                    datum=tx.datum,
                    bedrag=tx.bedrag,
                    merchant_name=tx.merchant_name,
                    naam=tx.naam,
                    omschrijving=tx.omschrijving,
                )
                for tx in sorted_txs
            ],
        ))
    result.sort(key=lambda x: x.total, reverse=True)
    return result


@router.post("/categorize-selected")
def categorize_selected(data: CategorizeSelectedRequest, db: Session = Depends(get_db)):
    """Assign a category to specific uncategorized transactions by ID."""
    if not data.transaction_ids:
        raise HTTPException(status_code=400, detail="No transaction IDs provided")

    cat = db.get(Category, data.category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    uncategorized_ids = set(
        db.execute(_uncategorized_query().where(Transaction.id.in_(data.transaction_ids)))
        .scalars()
        .all()
    )

    for tx in uncategorized_ids:
        tx.category_id = data.category_id

    db.commit()
    return {"updated": len(uncategorized_ids)}


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
