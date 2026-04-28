"""add imported exports audit table

Revision ID: g7h8i9j0k1l2
Revises: a1b2c3d4e5f7
Create Date: 2026-04-28 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'imported_exports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('export_id', sa.String(length=36), nullable=False),
        sa.Column('imported_at', sa.DateTime(), nullable=False),
        sa.Column('transactions_added', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('transactions_updated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('categories_added', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('export_id'),
    )


def downgrade() -> None:
    op.drop_table('imported_exports')
