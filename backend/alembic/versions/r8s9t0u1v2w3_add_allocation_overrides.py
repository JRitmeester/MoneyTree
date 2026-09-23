"""add allocation_overrides table

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-09-23 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'r8s9t0u1v2w3'
down_revision: Union[str, None] = 'q7r8s9t0u1v2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'allocation_overrides',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bucket_id', sa.Integer(), nullable=False),
        sa.Column('payday', sa.Date(), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['bucket_id'], ['allocation_buckets.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('bucket_id', 'payday', name='uq_override_bucket_payday'),
    )


def downgrade() -> None:
    op.drop_table('allocation_overrides')
