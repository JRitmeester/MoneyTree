"""add group_key column to recurring_payments

Detector v2: recurring payments are now detected per amount cluster within
a (counterparty/merchant, direction) group, so a single base key can
produce several candidates (e.g. a salary cluster and an expense-claim
cluster sharing one IBAN). `group_key` is the stable composite identity
("{base_key}|{income|expense}|{cluster index}") the detector uses to
refresh a suggested row in place across reruns instead of duplicating it.

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-08-28 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'o5p6q7r8s9t0'
down_revision: Union[str, None] = 'n4o5p6q7r8s9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'recurring_payments',
        sa.Column('group_key', sa.String(length=400), nullable=False, server_default=''),
    )


def downgrade() -> None:
    op.drop_column('recurring_payments', 'group_key')
