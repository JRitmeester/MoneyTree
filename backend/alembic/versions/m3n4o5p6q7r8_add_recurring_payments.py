"""add recurring_payments and recurring_payment_occurrences tables

Recurring-payment detection: suggested rows are refreshed in place by the
detector; confirmed/dismissed rows are never touched. Occurrences are kept
in a separate table (not a flag on transactions) so a detector re-run can
rebuild them without touching transaction rows.

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-08-28 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'm3n4o5p6q7r8'
down_revision: Union[str, None] = 'l2m3n4o5p6q7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'recurring_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('merchant_pattern', sa.String(length=255), nullable=False),
        sa.Column('counterparty_iban', sa.String(length=34), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('expected_amount', sa.Float(), nullable=False),
        sa.Column('amount_tolerance', sa.Float(), nullable=False, server_default='0.15'),
        sa.Column('cadence', sa.String(length=20), nullable=False),
        sa.Column('expected_day', sa.Integer(), nullable=True),
        sa.Column('anchor_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False, server_default='suggested'),
        sa.Column('category_id', sa.Integer(), sa.ForeignKey('categories.id'), nullable=True),
        sa.Column('is_income', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'recurring_payment_occurrences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recurring_payment_id', sa.Integer(),
                  sa.ForeignKey('recurring_payments.id'), nullable=False),
        sa.Column('transaction_id', sa.Integer(),
                  sa.ForeignKey('transactions.id'), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('transaction_id'),
    )


def downgrade() -> None:
    op.drop_table('recurring_payment_occurrences')
    op.drop_table('recurring_payments')
