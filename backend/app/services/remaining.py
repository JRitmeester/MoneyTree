"""Helper for managing the 'remaining' line item on receipts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from ..models import LineItem, Receipt


def recalculate_remaining(db: Session, receipt: Receipt, transaction_amount: float) -> LineItem | None:
    """Recalculate the remaining line item's amount based on explicit items and offsets.

    If remaining amount is 0 (or negative), delete the remaining line item.
    If remaining amount is positive and no remaining item exists, recreate one.
    """
    from ..models import LineItem, Transaction, TransactionOffset

    items = db.execute(
        select(LineItem).where(LineItem.receipt_id == receipt.id)
    ).scalars().all()

    explicit_sum = sum(
        li.amount * li.quantity
        for li in items
        if not li.is_remaining
    )

    # Calculate offset total (income transactions linked to this expense)
    offset_total = 0.0
    if receipt.transaction:
        offset_rows = db.execute(
            select(TransactionOffset).where(
                TransactionOffset.expense_transaction_id == receipt.transaction.id
            )
        ).scalars().all()
        for offset in offset_rows:
            income_tx = db.get(Transaction, offset.income_transaction_id)
            if income_tx:
                offset_total += abs(income_tx.bedrag)

    net_amount = abs(transaction_amount) - offset_total
    remaining_amount = round(net_amount - explicit_sum, 2)
    remaining = next((li for li in items if li.is_remaining), None)

    if remaining_amount <= 0:
        # Fully accounted for — remove remaining item and sync tx.categorie
        if remaining:
            db.delete(remaining)
        # Update tx.categorie to the category of the highest-amount explicit item
        if receipt.transaction:
            explicit_items = [li for li in items if not li.is_remaining and li.category]
            if explicit_items:
                best = max(explicit_items, key=lambda li: li.amount * li.quantity)
                receipt.transaction.categorie = best.category
        return None
    else:
        if remaining:
            remaining.amount = remaining_amount
        else:
            # Recreate remaining item
            category = None
            if receipt.transaction:
                category = receipt.transaction.categorie
            remaining = LineItem(
                receipt_id=receipt.id,
                description="Remaining",
                amount=remaining_amount,
                quantity=1,
                category=category,
                sort_order=999,
                is_remaining=True,
            )
            db.add(remaining)
        return remaining
