from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Category, LineItem, Receipt, Transaction
from ..schemas import (
    ImportResult,
    LineItemCreate,
    LineItemOut,
    MatchCandidate,
    MatchResult,
    TransactionDetail,
    TransactionListResponse,
    TransactionOut,
)
from ..services.csv_parser import parse_asn_csv

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.post("/import", response_model=ImportResult)
async def import_csv(
    file: UploadFile = File(...),
    update_duplicates: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Import an ASN Bank CSV export."""
    content = await file.read()
    parsed = parse_asn_csv(content)

    imported = 0
    skipped = 0
    updated = 0

    for tx_data in parsed:
        # Check for duplicate
        existing = db.execute(
            select(Transaction).where(Transaction.import_hash == tx_data["import_hash"])
        ).scalar_one_or_none()

        if existing:
            if update_duplicates:
                for key, value in tx_data.items():
                    if key != "import_hash":
                        setattr(existing, key, value)
                updated += 1
            else:
                skipped += 1
                continue

        if not existing:
            tx = Transaction(**tx_data)
            db.add(tx)
            imported += 1

        # Seed bank categories
        cat_name = tx_data["categorie"]
        if cat_name:
            existing_cat = db.execute(
                select(Category).where(Category.name == cat_name)
            ).scalar_one_or_none()
            if not existing_cat:
                db.add(Category(name=cat_name, is_bank_category=True))

    db.commit()

    # Run matching against unlinked receipts
    from ..services.matcher import find_matches

    unlinked_receipts = db.execute(
        select(Receipt).where(Receipt.transaction_id.is_(None))
    ).scalars().all()

    new_transactions = db.execute(
        select(Transaction).where(~Transaction.id.in_(
            select(Receipt.transaction_id).where(Receipt.transaction_id.is_not(None))
        ))
    ).scalars().all()

    matches = find_matches(list(unlinked_receipts), list(new_transactions))

    auto_linked = 0
    pending = []

    for match in matches:
        if match["auto_link"]:
            receipt = db.get(Receipt, match["receipt_id"])
            receipt.transaction_id = match["transaction_id"]
            receipt.match_confidence = match["confidence"]
            auto_linked += 1
        else:
            receipt = db.get(Receipt, match["receipt_id"])
            tx = db.get(Transaction, match["transaction_id"])
            pending.append(MatchCandidate(
                receipt_id=match["receipt_id"],
                transaction_id=match["transaction_id"],
                confidence=match["confidence"],
                receipt_merchant=receipt.merchant_name if receipt else None,
                transaction_merchant=tx.merchant_name if tx else None,
                receipt_amount=receipt.total_amount if receipt else None,
                transaction_amount=tx.bedrag if tx else 0,
            ))

    db.commit()

    return ImportResult(
        imported=imported,
        skipped_duplicates=skipped,
        updated=updated,
        matches=MatchResult(
            auto_linked=auto_linked,
            pending_confirmation=pending,
        ),
    )


@router.get("", response_model=TransactionListResponse)
def list_transactions(
    date_from: date | None = None,
    date_to: date | None = None,
    categorie: str | None = None,
    search: str | None = None,
    has_receipt: bool | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List transactions with filters."""
    query = select(Transaction).order_by(Transaction.datum.desc(), Transaction.id.desc())

    if date_from:
        query = query.where(Transaction.datum >= date_from)
    if date_to:
        query = query.where(Transaction.datum <= date_to)
    if categorie:
        query = query.where(Transaction.categorie == categorie)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            Transaction.omschrijving.ilike(pattern)
            | Transaction.merchant_name.ilike(pattern)
            | Transaction.naam.ilike(pattern)
        )
    if has_receipt is not None:
        receipt_tx_ids = select(Receipt.transaction_id).where(
            Receipt.transaction_id.is_not(None)
        )
        if has_receipt:
            query = query.where(Transaction.id.in_(receipt_tx_ids))
        else:
            query = query.where(~Transaction.id.in_(receipt_tx_ids))

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar()

    # Paginate
    results = db.execute(
        query.offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()

    # Check which have receipts
    tx_ids = [tx.id for tx in results]
    receipt_tx_ids_set = set()
    if tx_ids:
        rows = db.execute(
            select(Receipt.transaction_id).where(
                Receipt.transaction_id.in_(tx_ids)
            )
        ).scalars().all()
        receipt_tx_ids_set = set(rows)

    items = []
    for tx in results:
        out = TransactionOut.model_validate(tx)
        out.has_receipt = tx.id in receipt_tx_ids_set
        items.append(out)

    return TransactionListResponse(
        items=items, total=total, page=page, per_page=per_page
    )


@router.get("/{transaction_id}", response_model=TransactionDetail)
def get_transaction(transaction_id: int, db: Session = Depends(get_db)):
    """Get a single transaction with its receipt."""
    tx = db.get(Transaction, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    detail = TransactionDetail.model_validate(tx)
    detail.has_receipt = tx.receipt is not None
    if tx.receipt and tx.receipt.line_items:
        detail.line_items = [LineItemOut.model_validate(li) for li in tx.receipt.line_items]
    return detail


@router.patch("/{transaction_id}", response_model=TransactionOut)
def update_transaction(transaction_id: int, data: dict, db: Session = Depends(get_db)):
    """Update a transaction's category."""
    tx = db.get(Transaction, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if "categorie" in data:
        tx.categorie = data["categorie"]

    db.commit()
    db.refresh(tx)
    out = TransactionOut.model_validate(tx)
    out.has_receipt = tx.receipt is not None
    return out


@router.put("/{transaction_id}/line-items", response_model=list[LineItemOut])
def save_transaction_line_items(
    transaction_id: int,
    items: list[LineItemCreate],
    db: Session = Depends(get_db),
):
    """Save line items on a transaction. Auto-creates a virtual receipt if needed."""
    tx = db.get(Transaction, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Auto-create receipt if transaction has none
    if not tx.receipt:
        receipt = Receipt(
            transaction_id=tx.id,
            date=tx.datum,
            total_amount=abs(tx.bedrag),
            merchant_name=tx.merchant_name or tx.naam,
            image_path=None,
        )
        db.add(receipt)
        db.flush()
    else:
        receipt = tx.receipt

    # Bulk-replace line items
    for existing in list(receipt.line_items):
        db.delete(existing)
    db.flush()

    new_items = []
    for i, item_data in enumerate(items):
        li = LineItem(
            receipt_id=receipt.id,
            description=item_data.description,
            amount=item_data.amount,
            quantity=item_data.quantity,
            category=item_data.category,
            sort_order=item_data.sort_order if item_data.sort_order else i,
        )
        db.add(li)
        new_items.append(li)

    db.commit()
    for li in new_items:
        db.refresh(li)

    return [LineItemOut.model_validate(li) for li in new_items]
