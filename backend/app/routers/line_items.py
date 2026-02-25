from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import LineItem, Receipt
from ..schemas import LineItemCreate, LineItemOut, LineItemUpdate

router = APIRouter(tags=["line_items"])


@router.get("/api/line-items/categories", response_model=list[str])
def get_categories(q: str = Query("", min_length=0), db: Session = Depends(get_db)):
    """Return distinct individual category values (split from comma-separated), filtered by substring."""
    rows = db.execute(
        select(LineItem.category).where(LineItem.category.isnot(None))
    ).scalars().all()

    categories: set[str] = set()
    for raw in rows:
        for part in raw.split(","):
            stripped = part.strip()
            if stripped:
                categories.add(stripped)

    q_lower = q.lower()
    matched = sorted(c for c in categories if q_lower in c.lower())
    return matched


@router.get("/api/receipts/{receipt_id}/line-items", response_model=list[LineItemOut])
def list_line_items(receipt_id: int, db: Session = Depends(get_db)):
    """List line items for a receipt."""
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    items = db.execute(
        select(LineItem)
        .where(LineItem.receipt_id == receipt_id)
        .order_by(LineItem.sort_order)
    ).scalars().all()
    return items


@router.post("/api/receipts/{receipt_id}/line-items", response_model=LineItemOut)
def create_line_item(receipt_id: int, data: LineItemCreate, db: Session = Depends(get_db)):
    """Add a line item to a receipt."""
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    item = LineItem(receipt_id=receipt_id, **data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/api/receipts/{receipt_id}/line-items", response_model=list[LineItemOut])
def bulk_replace_line_items(
    receipt_id: int, items: list[LineItemCreate], db: Session = Depends(get_db)
):
    """Replace all line items for a receipt (used after OCR review)."""
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    # Delete existing
    db.execute(
        select(LineItem).where(LineItem.receipt_id == receipt_id)
    )
    for old in receipt.line_items:
        db.delete(old)

    # Create new
    new_items = []
    for i, item_data in enumerate(items):
        item = LineItem(
            receipt_id=receipt_id,
            sort_order=i,
            **item_data.model_dump(exclude={"sort_order"}),
        )
        db.add(item)
        new_items.append(item)

    db.commit()
    for item in new_items:
        db.refresh(item)
    return new_items


@router.patch("/api/line-items/{item_id}", response_model=LineItemOut)
def update_line_item(item_id: int, data: LineItemUpdate, db: Session = Depends(get_db)):
    """Update a line item."""
    item = db.get(LineItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Line item not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)

    db.commit()
    db.refresh(item)
    return item


@router.delete("/api/line-items/{item_id}")
def delete_line_item(item_id: int, db: Session = Depends(get_db)):
    """Delete a line item."""
    item = db.get(LineItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Line item not found")

    db.delete(item)
    db.commit()
    return {"ok": True}
