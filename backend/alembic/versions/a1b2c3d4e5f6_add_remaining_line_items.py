"""add_remaining_line_items

Revision ID: a1b2c3d4e5f6
Revises: c11280e1007c
Create Date: 2026-02-26

"""
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'c11280e1007c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add is_remaining column to line_items
    with op.batch_alter_table('line_items', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('is_remaining', sa.Boolean(), nullable=False, server_default='0')
        )

    # 2. Backfill: ensure every transaction has a receipt + remaining line item
    conn = op.get_bind()

    transactions = conn.execute(sa.text(
        "SELECT id, datum, bedrag, categorie, merchant_name, naam FROM transactions"
    )).fetchall()

    now = datetime.utcnow().isoformat()

    for tx in transactions:
        tx_id, datum, bedrag, categorie, merchant_name, naam = tx

        # Check if receipt exists
        receipt_row = conn.execute(
            sa.text("SELECT id FROM receipts WHERE transaction_id = :tid"),
            {"tid": tx_id}
        ).fetchone()

        if receipt_row is None:
            # Create virtual receipt
            conn.execute(sa.text(
                "INSERT INTO receipts (transaction_id, date, total_amount, merchant_name, created_at) "
                "VALUES (:tid, :date, :amount, :merchant, :now)"
            ), {
                "tid": tx_id,
                "date": datum,
                "amount": abs(bedrag),
                "merchant": merchant_name or naam,
                "now": now,
            })
            receipt_id = conn.execute(sa.text("SELECT last_insert_rowid()")).scalar()
        else:
            receipt_id = receipt_row[0]

        # Sum existing explicit line items
        existing_sum = conn.execute(
            sa.text(
                "SELECT COALESCE(SUM(amount * quantity), 0) "
                "FROM line_items WHERE receipt_id = :rid AND is_remaining = 0"
            ),
            {"rid": receipt_id}
        ).scalar()

        remaining_amount = round(abs(bedrag) - existing_sum, 2)

        # Create remaining line item
        conn.execute(sa.text(
            "INSERT INTO line_items (receipt_id, description, amount, quantity, category, sort_order, is_remaining) "
            "VALUES (:rid, 'Remaining', :amount, 1, :category, 999, 1)"
        ), {
            "rid": receipt_id,
            "amount": remaining_amount,
            "category": categorie,
        })


def downgrade() -> None:
    conn = op.get_bind()

    # Delete all remaining line items
    conn.execute(sa.text("DELETE FROM line_items WHERE is_remaining = 1"))

    # Delete virtual receipts (those with no image_path and no non-remaining line items)
    conn.execute(sa.text(
        "DELETE FROM receipts WHERE image_path IS NULL "
        "AND id NOT IN (SELECT DISTINCT receipt_id FROM line_items)"
    ))

    with op.batch_alter_table('line_items', schema=None) as batch_op:
        batch_op.drop_column('is_remaining')
