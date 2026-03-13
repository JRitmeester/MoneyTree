from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import LineItem, Receipt, Transaction

router = APIRouter(prefix="/api/debug", tags=["debug"], dependencies=[Depends(require_auth)])


class VirtualReceipt(BaseModel):
    receipt_id: int
    transaction_id: int
    transaction_date: str
    transaction_merchant: str | None
    transaction_amount: float


def _virtual_receipt_query():
    """Receipts with no image and only a remaining line item (auto-created on import)."""
    return (
        select(Receipt, Transaction)
        .join(Transaction, Receipt.transaction_id == Transaction.id)
        .where(Receipt.image_path.is_(None))
        .where(Receipt.transaction_id.is_not(None))
        .where(
            ~select(LineItem.id)
            .where(LineItem.receipt_id == Receipt.id)
            .where(LineItem.is_remaining == False)  # noqa: E712
            .exists()
        )
        .order_by(Transaction.datum.desc())
    )


@router.get("/virtual-receipts", response_model=list[VirtualReceipt])
def list_virtual_receipts(db: Session = Depends(get_db)):
    """List auto-created receipts that only contain a Remaining line item."""
    rows = db.execute(_virtual_receipt_query()).all()
    return [
        VirtualReceipt(
            receipt_id=receipt.id,
            transaction_id=tx.id,
            transaction_date=tx.datum.isoformat(),
            transaction_merchant=tx.merchant_name or tx.naam,
            transaction_amount=tx.bedrag,
        )
        for receipt, tx in rows
    ]


@router.delete("/virtual-receipts/{receipt_id}")
def delete_virtual_receipt(receipt_id: int, db: Session = Depends(get_db)):
    """Delete a single virtual receipt (only if it has no real image and no explicit items)."""
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Receipt not found")
    if receipt.image_path is not None:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Receipt has an image — not a virtual receipt")
    has_explicit = db.execute(
        select(LineItem.id)
        .where(LineItem.receipt_id == receipt_id)
        .where(LineItem.is_remaining == False)  # noqa: E712
    ).first()
    if has_explicit:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Receipt has explicit line items")

    db.delete(receipt)
    db.commit()
    return {"ok": True}


@router.delete("/virtual-receipts")
def delete_all_virtual_receipts(db: Session = Depends(get_db)):
    """Delete all virtual receipts (no image, only Remaining item)."""
    rows = db.execute(_virtual_receipt_query()).all()
    count = 0
    for receipt, _ in rows:
        db.delete(receipt)
        count += 1
    db.commit()
    return {"deleted": count}
