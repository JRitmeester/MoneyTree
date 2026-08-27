"""add own_accounts table and transaction transfer/incidental flags

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-08-27 15:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'j0k1l2m3n4o5'
down_revision: Union[str, None] = 'i9j0k1l2m3n4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'own_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('iban', sa.String(length=34), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('account_type', sa.String(length=10), nullable=False),
        sa.Column('starting_balance', sa.Float(), nullable=True),
        sa.Column('starting_balance_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('iban'),
    )
    op.add_column('transactions', sa.Column(
        'is_internal_transfer', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('transactions', sa.Column(
        'is_internal_transfer_manual', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('transactions', sa.Column(
        'is_incidental', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('transactions', 'is_incidental')
    op.drop_column('transactions', 'is_internal_transfer_manual')
    op.drop_column('transactions', 'is_internal_transfer')
    op.drop_table('own_accounts')
