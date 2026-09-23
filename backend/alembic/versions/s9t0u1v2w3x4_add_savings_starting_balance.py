"""add categories.savings_starting_balance

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-09-23 17:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 's9t0u1v2w3x4'
down_revision: Union[str, None] = 'r8s9t0u1v2w3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('categories', sa.Column('savings_starting_balance', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('categories', 'savings_starting_balance')
