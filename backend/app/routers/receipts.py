import uuid
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import UPLOADS_DIR
from ..database import get_db
from ..models import LineItem, Receipt, Transaction
from ..services.remaining import recalculate_remaining
from ..schemas import (
    ReceiptCreateResponse,
    ReceiptDetail,
    ReceiptOut,
    ReceiptUpdate,
    LineItemOut,
    OcrLineItem,
    OcrResult,
)
from ..services.ocr import process_receipt

router = APIRouter(prefix="/api/receipts", tags=["receipts"])


def _save_upload(file: UploadFile) -> str:
    """Save uploaded file and return relative path."""
    today = datetime.now()
    dir_path = UPLOADS_DIR / str(today.year) / f"{today.month:02d}"
    dir_path.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename or "receipt.jpg").suffix or ".jpg"
    filename = f"receipt_{uuid.uuid4().hex[:12]}{ext}"
    file_path = dir_path / filename

    with open(file_path, "wb") as f:
        f.write(file.file.read())

    return str(file_path.relative_to(UPLOADS_DIR))


@router.post("", response_model=ReceiptCreateResponse)
async def create_receipt(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a receipt image, run OCR, return extracted data."""
    relative_path = _save_upload(file)
    absolute_path = str(UPLOADS_DIR / relative_path)

    # Run OCR
    ocr_data = process_receipt(absolute_path)

    # Parse date
    receipt_date = None
    if ocr_data["date"]:
        try:
            receipt_date = date.fromisoformat(ocr_data["date"])
        except ValueError:
            pass

    # Create receipt
    receipt = Receipt(
        image_path=relative_path,
        date=receipt_date,
        total_amount=ocr_data["total_amount"],
        merchant_name=ocr_data["merchant_name"],
        ocr_raw_text=ocr_data["raw_text"],
    )
    db.add(receipt)
    db.flush()

    # Create line items from OCR
    for i, item in enumerate(ocr_data["line_items"]):
        li = LineItem(
            receipt_id=receipt.id,
            description=item["description"],
            amount=item["amount"],
            quantity=item.get("quantity", 1),
            sort_order=i,
        )
        db.add(li)

    db.commit()
    db.refresh(receipt)

    # Try to match against unlinked transactions
    from ..services.matcher import find_matches

    unlinked_txs = db.execute(
        select(Transaction).where(~Transaction.id.in_(
            select(Receipt.transaction_id).where(Receipt.transaction_id.is_not(None))
        ))
    ).scalars().all()

    matches = find_matches([receipt], list(unlinked_txs))
    for match in matches:
        if match["auto_link"]:
            tx = db.get(Transaction, match["transaction_id"])

            # If transaction already has a virtual receipt, merge it
            existing_receipt = db.execute(
                select(Receipt).where(
                    Receipt.transaction_id == match["transaction_id"],
                    Receipt.id != receipt.id,
                )
            ).scalar_one_or_none()
            if existing_receipt:
                # Delete old virtual receipt's items (including remaining)
                for old_li in list(existing_receipt.line_items):
                    db.delete(old_li)
                db.delete(existing_receipt)
                db.flush()

            receipt.transaction_id = match["transaction_id"]
            receipt.match_confidence = match["confidence"]
            db.flush()

            # Add remaining line item
            remaining_li = LineItem(
                receipt_id=receipt.id,
                description="Remaining",
                amount=0,
                quantity=1,
                category=tx.categorie,
                sort_order=999,
                is_remaining=True,
            )
            db.add(remaining_li)
            db.flush()
            recalculate_remaining(db, receipt, tx.bedrag)
            db.commit()
            break

    return ReceiptCreateResponse(
        id=receipt.id,
        image_path=f"/uploads/{relative_path}",
        ocr_result=OcrResult(
            date=ocr_data["date"],
            total_amount=ocr_data["total_amount"],
            merchant_name=ocr_data["merchant_name"],
            line_items=[OcrLineItem(**item) for item in ocr_data["line_items"]],
            raw_text=ocr_data["raw_text"],
        ),
    )


@router.get("", response_model=list[ReceiptOut])
def list_receipts(
    unmatched: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    """List receipts."""
    query = select(Receipt).order_by(Receipt.created_at.desc())

    if unmatched is True:
        query = query.where(Receipt.transaction_id.is_(None))
    elif unmatched is False:
        query = query.where(Receipt.transaction_id.is_not(None))

    if date_from:
        query = query.where(Receipt.date >= date_from)
    if date_to:
        query = query.where(Receipt.date <= date_to)

    receipts = db.execute(query).scalars().all()
    result = []
    for r in receipts:
        out = ReceiptOut.model_validate(r)
        out.image_path = f"/uploads/{r.image_path}"
        result.append(out)
    return result


@router.get("/{receipt_id}", response_model=ReceiptDetail)
def get_receipt(receipt_id: int, db: Session = Depends(get_db)):
    """Get receipt with line items."""
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    detail = ReceiptDetail.model_validate(receipt)
    detail.image_path = f"/uploads/{receipt.image_path}"

    if receipt.transaction:
        from ..schemas import TransactionOut
        detail.transaction = TransactionOut.model_validate(receipt.transaction)
        detail.transaction.has_receipt = True

    return detail


@router.patch("/{receipt_id}", response_model=ReceiptOut)
def update_receipt(receipt_id: int, data: ReceiptUpdate, db: Session = Depends(get_db)):
    """Update receipt fields (correct OCR output)."""
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(receipt, field, value)

    db.commit()
    db.refresh(receipt)
    return receipt


@router.delete("/{receipt_id}")
def delete_receipt(receipt_id: int, db: Session = Depends(get_db)):
    """Delete receipt and its line items."""
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    # Delete image file
    image_file = UPLOADS_DIR / receipt.image_path
    if image_file.exists():
        image_file.unlink()

    db.delete(receipt)
    db.commit()
    return {"ok": True}


@router.post("/{receipt_id}/link/{transaction_id}", response_model=ReceiptOut)
def link_receipt(receipt_id: int, transaction_id: int, db: Session = Depends(get_db)):
    """Manually link a receipt to a transaction."""
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    tx = db.get(Transaction, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Check for existing virtual receipt on the transaction
    existing = db.execute(
        select(Receipt).where(
            Receipt.transaction_id == transaction_id,
            Receipt.id != receipt_id,
        )
    ).scalar_one_or_none()
    if existing:
        # Migrate explicit line items from virtual receipt to new receipt
        for li in list(existing.line_items):
            if not li.is_remaining:
                li.receipt_id = receipt.id
            else:
                db.delete(li)
        db.delete(existing)
        db.flush()

    receipt.transaction_id = transaction_id
    receipt.match_confidence = 1.0  # Manual link = full confidence
    db.flush()

    # Add remaining line item to the linked receipt
    remaining = next((li for li in receipt.line_items if li.is_remaining), None)
    if not remaining:
        remaining = LineItem(
            receipt_id=receipt.id,
            description="Remaining",
            amount=0,
            quantity=1,
            category=tx.categorie,
            sort_order=999,
            is_remaining=True,
        )
        db.add(remaining)
        db.flush()
    recalculate_remaining(db, receipt, tx.bedrag)

    db.commit()
    db.refresh(receipt)
    return receipt


@router.post("/{receipt_id}/unlink", response_model=ReceiptOut)
def unlink_receipt(receipt_id: int, db: Session = Depends(get_db)):
    """Remove link between receipt and transaction."""
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    # Remove remaining line item (no transaction amount to reference)
    for li in list(receipt.line_items):
        if li.is_remaining:
            db.delete(li)

    receipt.transaction_id = None
    receipt.match_confidence = None
    db.commit()
    db.refresh(receipt)
    return receipt


@router.post("/match", response_model=list["MatchCandidate"])
def trigger_matching(db: Session = Depends(get_db)):
    """Re-run matching for all unlinked receipts against unlinked transactions."""
    from ..schemas import MatchCandidate
    from ..services.matcher import find_matches

    unlinked_receipts = db.execute(
        select(Receipt).where(Receipt.transaction_id.is_(None))
    ).scalars().all()

    unlinked_txs = db.execute(
        select(Transaction).where(~Transaction.id.in_(
            select(Receipt.transaction_id).where(Receipt.transaction_id.is_not(None))
        ))
    ).scalars().all()

    matches = find_matches(list(unlinked_receipts), list(unlinked_txs))

    candidates = []
    for match in matches:
        receipt = db.get(Receipt, match["receipt_id"])
        tx = db.get(Transaction, match["transaction_id"])
        if match["auto_link"]:
            receipt.transaction_id = match["transaction_id"]
            receipt.match_confidence = match["confidence"]
        else:
            candidates.append(MatchCandidate(
                receipt_id=match["receipt_id"],
                transaction_id=match["transaction_id"],
                confidence=match["confidence"],
                receipt_merchant=receipt.merchant_name if receipt else None,
                transaction_merchant=tx.merchant_name if tx else None,
                receipt_amount=receipt.total_amount if receipt else None,
                transaction_amount=tx.bedrag if tx else 0,
            ))

    db.commit()
    return candidates
