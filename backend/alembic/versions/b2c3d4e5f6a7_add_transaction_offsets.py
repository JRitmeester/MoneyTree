"""add_transaction_offsets

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'transaction_offsets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('expense_transaction_id', sa.Integer(), sa.ForeignKey('transactions.id'), nullable=False),
        sa.Column('income_transaction_id', sa.Integer(), sa.ForeignKey('transactions.id'), nullable=False, unique=True),
    )


def downgrade() -> None:
    op.drop_table('transaction_offsets')
