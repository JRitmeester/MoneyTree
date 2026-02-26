from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import LineItem, Receipt
from ..schemas import LineItemCreate, LineItemOut, LineItemUpdate
from ..services.remaining import recalculate_remaining

router = APIRouter(tags=["line_items"])


@router.get("/api/line-items/categories", response_model=list[str])
def get_categories(q: str = Query("", min_length=0), db: Session = Depends(get_db)):
    """Return distinct category values, filtered by substring."""
    rows = db.execute(
        select(LineItem.category).where(
            LineItem.category.isnot(None),
            LineItem.category != "",
        ).distinct()
    ).scalars().all()

    categories = {c.strip() for c in rows if c and c.strip()}
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

    item = LineItem(receipt_id=receipt_id, is_remaining=False, **data.model_dump())
    db.add(item)
    db.flush()

    # Recalculate remaining if receipt is linked to a transaction
    if receipt.transaction:
        recalculate_remaining(db, receipt, receipt.transaction.bedrag)

    db.commit()
    db.refresh(item)
    return item


@router.put("/api/receipts/{receipt_id}/line-items", response_model=list[LineItemOut])
def bulk_replace_line_items(
    receipt_id: int, items: list[LineItemCreate], db: Session = Depends(get_db)
):
    """Replace all explicit (non-remaining) line items for a receipt."""
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    # Only delete non-remaining items
    for old in list(receipt.line_items):
        if not old.is_remaining:
            db.delete(old)
    db.flush()

    # Create new explicit items
    new_items = []
    for i, item_data in enumerate(items):
        item = LineItem(
            receipt_id=receipt_id,
            sort_order=i,
            is_remaining=False,
            **item_data.model_dump(exclude={"sort_order"}),
        )
        db.add(item)
        new_items.append(item)

    db.flush()

    # Recalculate remaining if receipt is linked to a transaction
    if receipt.transaction:
        recalculate_remaining(db, receipt, receipt.transaction.bedrag)

    db.commit()
    for item in new_items:
        db.refresh(item)

    # Include remaining item in response
    remaining = next((li for li in receipt.line_items if li.is_remaining), None)
    result = [LineItemOut.model_validate(item) for item in new_items]
    if remaining:
        db.refresh(remaining)
        result.append(LineItemOut.model_validate(remaining))
    return result


@router.patch("/api/line-items/{item_id}", response_model=LineItemOut)
def update_line_item(item_id: int, data: LineItemUpdate, db: Session = Depends(get_db)):
    """Update a line item."""
    item = db.get(LineItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Line item not found")

    updates = data.model_dump(exclude_unset=True)

    # If updating a remaining item's category, sync to transaction
    if item.is_remaining and "category" in updates:
        if item.receipt and item.receipt.transaction:
            item.receipt.transaction.categorie = updates["category"] or ""

    # Don't allow changing is_remaining flag
    updates.pop("is_remaining", None)

    for field, value in updates.items():
        setattr(item, field, value)

    # Recalculate remaining if a non-remaining item's amount changed
    if not item.is_remaining and "amount" in updates:
        if item.receipt and item.receipt.transaction:
            recalculate_remaining(db, item.receipt, item.receipt.transaction.bedrag)

    db.commit()
    db.refresh(item)
    return item


@router.delete("/api/line-items/{item_id}")
def delete_line_item(item_id: int, db: Session = Depends(get_db)):
    """Delete a line item."""
    item = db.get(LineItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Line item not found")

    if item.is_remaining:
        raise HTTPException(status_code=400, detail="Cannot delete the remaining line item")

    receipt = item.receipt
    db.delete(item)
    db.flush()

    # Recalculate remaining
    if receipt.transaction:
        recalculate_remaining(db, receipt, receipt.transaction.bedrag)

    db.commit()
    return {"ok": True}
