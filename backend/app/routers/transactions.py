import re
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import Category, CategoryMapping, IncidentalLabel, LineItem, Receipt, Transaction, TransactionOffset
from ..services.remaining import recalculate_remaining
from ..services.transfers import is_internal, own_ibans
from ..schemas import (
    BulkFlagsRequest,
    ImportResult,
    LineItemCreate,
    LineItemOut,
    MatchCandidate,
    MatchResult,
    TransactionDetail,
    TransactionListResponse,
    TransactionOut,
)
from ..services.csv_parser import CsvFormatError, parse_asn_csv

router = APIRouter(prefix="/api/transactions", tags=["transactions"], dependencies=[Depends(require_auth)])


def _collect_descendant_ids(db: Session, category_id: int) -> set[int]:
    """Return category_id plus all descendant category IDs."""
    all_cats = db.execute(select(Category.id, Category.parent_id)).all()
    children_map: dict[int | None, list[int]] = {}
    for cid, pid in all_cats:
        children_map.setdefault(pid, []).append(cid)

    result: set[int] = set()
    stack = [category_id]
    while stack:
        current = stack.pop()
        result.add(current)
        stack.extend(children_map.get(current, []))
    return result


_AMOUNT_PATTERN = re.compile(r"^-?\s*€?\s*\d+(?:[.,]\d+)?$")


def _parse_amount(search: str) -> float | None:
    """Parse a search string as a monetary amount, or return None.

    Accepts Dutch comma or dot decimal separators, an optional leading minus
    sign, and an optional euro sign, e.g. "46", "46,95", "46.95", "-46,95",
    "€46,95". The sign is irrelevant to matching since it compares against
    abs(bedrag), so the returned value is always non-negative."""
    text = search.strip()
    if not text or not _AMOUNT_PATTERN.match(text):
        return None
    cleaned = text.replace("€", "").replace("-", "").replace(" ", "")
    cleaned = cleaned.replace(",", ".")
    try:
        return abs(float(cleaned))
    except ValueError:
        return None


def _category_id_for_categorie(categorie: str, db: Session) -> int | None:
    """Look up a user category_id from the bank's categorie string via CategoryMapping."""
    mapping = db.execute(
        select(CategoryMapping).where(CategoryMapping.bank_category == categorie)
    ).scalar_one_or_none()
    return mapping.category_id if mapping else None


@router.post("/import", response_model=ImportResult)
async def import_csv(
    file: UploadFile = File(...),
    update_duplicates: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Import an ASN Bank CSV export."""
    content = await file.read()
    try:
        parsed = parse_asn_csv(content)
    except CsvFormatError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=400, detail="This does not look like an ASN Bank CSV export"
        )

    imported = 0
    skipped = 0
    updated = 0
    categorized = 0
    uncategorized = 0
    ibans = own_ibans(db)

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
                # Re-resolve category_id in case mapping changed
                existing.category_id = _category_id_for_categorie(existing.categorie, db)
                if not existing.is_internal_transfer_manual:
                    existing.is_internal_transfer = is_internal(existing, ibans)
                updated += 1
            else:
                skipped += 1
                continue

        if not existing:
            tx = Transaction(**tx_data)
            # Set user category from mapping
            tx.category_id = _category_id_for_categorie(tx_data["categorie"], db)
            tx.is_internal_transfer = is_internal(tx, ibans)
            db.add(tx)
            imported += 1
            if tx.category_id is not None:
                categorized += 1
            else:
                uncategorized += 1

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
        categorized=categorized,
        uncategorized=uncategorized,
        matches=MatchResult(
            auto_linked=auto_linked,
            pending_confirmation=pending,
        ),
    )


@router.get("", response_model=TransactionListResponse)
def list_transactions(
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: int | None = None,
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
    if category_id is not None:
        # Collect the selected category and all its descendants
        cat_ids = _collect_descendant_ids(db, category_id)

        # Match transactions by direct category_id OR line item category
        matching_tx_ids = (
            select(Transaction.id)
            .join(Receipt, Receipt.transaction_id == Transaction.id)
            .join(LineItem, LineItem.receipt_id == Receipt.id)
            .where(LineItem.category_id.in_(cat_ids))
        )
        query = query.where(
            Transaction.category_id.in_(cat_ids)
            | Transaction.id.in_(matching_tx_ids)
        )
    if search:
        pattern = f"%{search}%"
        text_match = (
            Transaction.omschrijving.ilike(pattern)
            | Transaction.merchant_name.ilike(pattern)
            | Transaction.naam.ilike(pattern)
        )
        amount = _parse_amount(search)
        if amount is not None:
            query = query.where(
                text_match | (func.abs(Transaction.bedrag) - amount).between(-0.005, 0.005)
            )
        else:
            query = query.where(text_match)
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


@router.post("/bulk-flags")
def bulk_set_flags(payload: BulkFlagsRequest, db: Session = Depends(get_db)):
    """Set incidental/transfer flags on many transactions at once.

    Assigning a label implies incidental; clearing incidental clears the label.
    Setting the transfer flag marks the rows as manual so backfills skip them."""
    if payload.incidental_label_id is not None:
        if not db.get(IncidentalLabel, payload.incidental_label_id):
            raise HTTPException(status_code=404, detail="Label not found")

    txs = db.execute(
        select(Transaction).where(Transaction.id.in_(payload.transaction_ids))
    ).scalars().all()
    for tx in txs:
        if payload.is_internal_transfer is not None:
            tx.is_internal_transfer = payload.is_internal_transfer
            tx.is_internal_transfer_manual = True
        if payload.is_incidental is False:
            tx.is_incidental = False
            tx.incidental_label_id = None
        elif payload.incidental_label_id is not None:
            tx.is_incidental = True
            tx.incidental_label_id = payload.incidental_label_id
        elif payload.is_incidental is True:
            tx.is_incidental = True
    db.commit()
    return {"updated": len(txs)}


@router.get("/{transaction_id}", response_model=TransactionDetail)
def get_transaction(transaction_id: int, db: Session = Depends(get_db)):
    """Get a single transaction with its receipt and offsets."""
    tx = db.get(Transaction, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    detail = TransactionDetail.model_validate(tx)
    detail.has_receipt = tx.receipt is not None
    if tx.receipt and tx.receipt.line_items:
        detail.line_items = [LineItemOut.model_validate(li) for li in tx.receipt.line_items]

    # Load offsets (income txs that offset this expense)
    offset_rows = db.execute(
        select(TransactionOffset).where(
            TransactionOffset.expense_transaction_id == tx.id
        )
    ).scalars().all()
    for offset in offset_rows:
        income_tx = db.get(Transaction, offset.income_transaction_id)
        if income_tx:
            out = TransactionOut.model_validate(income_tx)
            out.has_receipt = income_tx.receipt is not None
            detail.offsets.append(out)

    # Check if this tx is an offset for an expense
    offset_of = db.execute(
        select(TransactionOffset).where(
            TransactionOffset.income_transaction_id == tx.id
        )
    ).scalar_one_or_none()
    if offset_of:
        expense_tx = db.get(Transaction, offset_of.expense_transaction_id)
        if expense_tx:
            out = TransactionOut.model_validate(expense_tx)
            out.has_receipt = expense_tx.receipt is not None
            detail.offsets_expense = out

    return detail


@router.post("/{transaction_id}/split-receipt")
def split_receipt(transaction_id: int, db: Session = Depends(get_db)):
    """Create an empty virtual receipt for a transaction so it can be split into line items."""
    tx = db.get(Transaction, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if tx.receipt:
        return {"receipt_id": tx.receipt.id}

    receipt = Receipt(
        transaction_id=tx.id,
        date=tx.datum,
        total_amount=abs(tx.bedrag),
        merchant_name=tx.merchant_name or tx.naam,
    )
    db.add(receipt)
    db.flush()

    remaining = LineItem(
        receipt_id=receipt.id,
        description="Remaining",
        amount=abs(tx.bedrag),
        quantity=1,
        category_id=tx.category_id,
        sort_order=999,
        is_remaining=True,
    )
    db.add(remaining)
    db.commit()
    return {"receipt_id": receipt.id}


@router.patch("/{transaction_id}", response_model=TransactionOut)
def update_transaction(transaction_id: int, data: dict, db: Session = Depends(get_db)):
    """Update a transaction's category."""
    tx = db.get(Transaction, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if "category_id" in data:
        cat_id = data["category_id"]
        # Validate category exists
        if cat_id is not None and not db.get(Category, cat_id):
            raise HTTPException(status_code=404, detail="Category not found")
        tx.category_id = cat_id
        # Sync to remaining line item
        if tx.receipt:
            for li in tx.receipt.line_items:
                if li.is_remaining:
                    li.category_id = cat_id
                    break

    # is_incidental=False wins over a supplied label, matching bulk_set_flags.
    if data.get("is_incidental") is False:
        tx.is_incidental = False
        tx.incidental_label_id = None
    else:
        if "is_incidental" in data:
            tx.is_incidental = bool(data["is_incidental"])
        if "incidental_label_id" in data:
            label_id = data["incidental_label_id"]
            if label_id is not None:
                if not db.get(IncidentalLabel, label_id):
                    raise HTTPException(status_code=404, detail="Label not found")
                tx.is_incidental = True
            tx.incidental_label_id = label_id

    if "is_internal_transfer" in data:
        tx.is_internal_transfer = bool(data["is_internal_transfer"])
        tx.is_internal_transfer_manual = True

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

        # Create remaining line item
        remaining_li = LineItem(
            receipt_id=receipt.id,
            description="Remaining",
            amount=abs(tx.bedrag),
            quantity=1,
            category_id=tx.category_id,
            sort_order=999,
            is_remaining=True,
        )
        db.add(remaining_li)
        db.flush()
    else:
        receipt = tx.receipt

    # Only delete non-remaining line items
    for existing in list(receipt.line_items):
        if not existing.is_remaining:
            db.delete(existing)
    db.flush()

    new_items = []
    for i, item_data in enumerate(items):
        li = LineItem(
            receipt_id=receipt.id,
            description=item_data.description,
            amount=item_data.amount,
            quantity=item_data.quantity,
            category_id=item_data.category_id,
            sort_order=item_data.sort_order if item_data.sort_order else i,
            is_remaining=False,
        )
        db.add(li)
        new_items.append(li)

    db.flush()
    recalculate_remaining(db, receipt, tx.bedrag)

    db.commit()
    for li in new_items:
        db.refresh(li)

    # Include remaining item in response
    remaining = next((li for li in receipt.line_items if li.is_remaining), None)
    result = [LineItemOut.model_validate(li) for li in new_items]
    if remaining:
        db.refresh(remaining)
        result.append(LineItemOut.model_validate(remaining))
    return result


@router.post("/{expense_id}/offsets/{income_id}")
def link_offset(expense_id: int, income_id: int, db: Session = Depends(get_db)):
    """Link an income transaction as an offset to an expense transaction."""
    expense_tx = db.get(Transaction, expense_id)
    if not expense_tx:
        raise HTTPException(status_code=404, detail="Expense transaction not found")
    income_tx = db.get(Transaction, income_id)
    if not income_tx:
        raise HTTPException(status_code=404, detail="Income transaction not found")

    if expense_tx.bedrag >= 0:
        raise HTTPException(status_code=400, detail="Expense transaction must have negative amount")
    if income_tx.bedrag <= 0:
        raise HTTPException(status_code=400, detail="Offset transaction must have positive amount")

    # Check income tx not already an offset
    existing = db.execute(
        select(TransactionOffset).where(
            TransactionOffset.income_transaction_id == income_id
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="This transaction is already linked as an offset")

    # Create offset link
    offset = TransactionOffset(
        expense_transaction_id=expense_id,
        income_transaction_id=income_id,
    )
    db.add(offset)
    db.flush()

    # Remove income tx's remaining line item
    if income_tx.receipt:
        for li in list(income_tx.receipt.line_items):
            if li.is_remaining:
                db.delete(li)
        db.flush()

    # Recalculate expense tx's remaining (now factors in this offset)
    if expense_tx.receipt:
        recalculate_remaining(db, expense_tx.receipt, expense_tx.bedrag)

    db.commit()
    return {"ok": True}


@router.delete("/{expense_id}/offsets/{income_id}")
def unlink_offset(expense_id: int, income_id: int, db: Session = Depends(get_db)):
    """Remove an offset link between transactions."""
    offset = db.execute(
        select(TransactionOffset).where(
            TransactionOffset.expense_transaction_id == expense_id,
            TransactionOffset.income_transaction_id == income_id,
        )
    ).scalar_one_or_none()
    if not offset:
        raise HTTPException(status_code=404, detail="Offset link not found")

    db.delete(offset)
    db.flush()

    # Recreate income tx's remaining line item
    income_tx = db.get(Transaction, income_id)
    if income_tx and income_tx.receipt:
        recalculate_remaining(db, income_tx.receipt, income_tx.bedrag)

    # Recalculate expense tx's remaining (offset removed, remaining goes up)
    expense_tx = db.get(Transaction, expense_id)
    if expense_tx and expense_tx.receipt:
        recalculate_remaining(db, expense_tx.receipt, expense_tx.bedrag)

    db.commit()
    return {"ok": True}
