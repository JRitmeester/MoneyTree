from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select, func
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import (
    AppSetting,
    Budget,
    BudgetLine,
    BudgetTemplate,
    Category,
    CategoryMapping,
    LineItem,
    OwnAccount,
    PasskeyCredential,
    Receipt,
    RecurringPayment,
    RecurringPaymentOccurrence,
    Transaction,
    TransactionOffset,
)

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(require_auth)],
)


# ---------- Virtual receipts (moved from debug router) ----------


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


# ---------- Delete all transactions ----------


@router.delete("/transactions")
def delete_all_transactions(db: Session = Depends(get_db)):
    """Delete ALL transactions and their associated receipts, line items, and offsets."""
    count = db.execute(select(func.count(Transaction.id))).scalar() or 0
    if count == 0:
        return {"deleted": 0}

    # Delete in FK dependency order
    # 1. Line items belonging to transaction-linked receipts
    db.execute(
        delete(LineItem).where(
            LineItem.receipt_id.in_(
                select(Receipt.id).where(Receipt.transaction_id.is_not(None))
            )
        )
    )
    # 2. Transaction offsets
    db.execute(delete(TransactionOffset))
    # 3. Receipts linked to transactions
    db.execute(delete(Receipt).where(Receipt.transaction_id.is_not(None)))
    # 4. Transactions
    db.execute(delete(Transaction))

    db.commit()
    return {"deleted": count}


# ---------- Delete all budgets ----------


@router.delete("/budgets")
def delete_all_budgets(db: Session = Depends(get_db)):
    """Delete ALL budgets, budget lines, and budget templates."""
    count = db.execute(select(func.count(Budget.id))).scalar() or 0

    # BudgetLine FK → budgets, categories
    db.execute(delete(BudgetLine))
    db.execute(delete(BudgetTemplate))
    db.execute(delete(Budget))

    db.commit()
    return {"deleted": count}


# ---------- Delete all receipts ----------


@router.delete("/receipts")
def delete_all_receipts(db: Session = Depends(get_db)):
    """Delete ALL receipts and their line items."""
    count = db.execute(select(func.count(Receipt.id))).scalar() or 0

    # LineItem FK → receipts
    db.execute(delete(LineItem))
    db.execute(delete(Receipt))

    db.commit()
    return {"deleted": count}


# ---------- Delete all categories ----------


@router.delete("/categories")
def delete_all_categories(db: Session = Depends(get_db)):
    """Delete ALL categories and clear all category references."""
    count = db.execute(select(func.count(Category.id))).scalar() or 0

    # Clear FK references to categories
    db.execute(delete(CategoryMapping))
    db.execute(delete(BudgetTemplate))
    db.execute(delete(BudgetLine))
    # Nullify category_id on line items and transactions
    from sqlalchemy import update
    db.execute(update(LineItem).values(category_id=None))
    db.execute(update(Transaction).values(category_id=None))
    # Nullify parent_id before deleting (self-referential FK)
    db.execute(update(Category).values(parent_id=None))
    db.execute(delete(Category))

    db.commit()
    return {"deleted": count}


# ---------- Delete everything ----------


@router.delete("/everything")
def delete_everything(db: Session = Depends(get_db)):
    """Delete ALL application data (transactions, receipts, budgets, categories)."""
    # Delete in FK dependency order
    db.execute(delete(RecurringPaymentOccurrence))
    db.execute(delete(RecurringPayment))
    db.execute(delete(LineItem))
    db.execute(delete(TransactionOffset))
    db.execute(delete(Receipt))
    db.execute(delete(CategoryMapping))
    db.execute(delete(BudgetTemplate))
    db.execute(delete(BudgetLine))
    db.execute(delete(Budget))
    db.execute(delete(Transaction))
    # Categories: nullify self-ref FK then delete
    from sqlalchemy import update
    db.execute(update(Category).values(parent_id=None))
    db.execute(delete(Category))
    db.execute(delete(OwnAccount))
    db.execute(delete(AppSetting))

    db.commit()
    return {"ok": True}


# ---------- Passkeys ----------


class PasskeySummary(BaseModel):
    id: int
    name: str
    created_at: str | None


@router.get("/passkeys", response_model=list[PasskeySummary])
def list_passkeys(db: Session = Depends(get_db)):
    """List all registered passkey credentials."""
    creds = db.execute(
        select(PasskeyCredential).order_by(PasskeyCredential.created_at.desc())
    ).scalars().all()
    return [
        PasskeySummary(
            id=c.id,
            name=c.name,
            created_at=c.created_at.isoformat() if c.created_at else None,
        )
        for c in creds
    ]


@router.delete("/passkeys/{passkey_id}")
def delete_passkey(passkey_id: int, db: Session = Depends(get_db)):
    """Delete a single passkey credential."""
    cred = db.get(PasskeyCredential, passkey_id)
    if not cred:
        raise HTTPException(status_code=404, detail="Passkey not found")
    db.delete(cred)
    db.commit()
    return {"ok": True}
