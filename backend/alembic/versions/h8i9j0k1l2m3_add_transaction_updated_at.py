"""add transactions.updated_at column

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-04-28 01:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'h8i9j0k1l2m3'
down_revision: Union[str, None] = 'g7h8i9j0k1l2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add column allowing NULL initially so existing rows can be backfilled
    op.add_column('transactions', sa.Column('updated_at', sa.DateTime(), nullable=True))
    # Backfill: every existing row's updated_at = its created_at
    op.execute("UPDATE transactions SET updated_at = created_at WHERE updated_at IS NULL")
    # Then make it NOT NULL
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.alter_column('updated_at', existing_type=sa.DateTime(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_column('updated_at')
