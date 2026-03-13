"""budget_date_range

Revision ID: d4e5f6a7b8c9
Revises: 83bb7d48475e
Create Date: 2026-03-01 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = '83bb7d48475e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable start_date and end_date columns
    op.add_column('budgets', sa.Column('start_date', sa.Date(), nullable=True))
    op.add_column('budgets', sa.Column('end_date', sa.Date(), nullable=True))

    # Data migration: convert (year, month) -> (first_of_month, last_of_month)
    op.execute("""
        UPDATE budgets
        SET start_date = DATE(year || '-' || PRINTF('%02d', month) || '-01'),
            end_date = DATE(year || '-' || PRINTF('%02d', month) || '-01', '+1 month', '-1 day')
    """)

    # Make columns non-nullable
    with op.batch_alter_table('budgets') as batch_op:
        batch_op.alter_column('start_date', nullable=False)
        batch_op.alter_column('end_date', nullable=False)

        # Drop old unique constraint and columns
        batch_op.drop_constraint('uq_budget_year_month', type_='unique')
        batch_op.drop_column('year')
        batch_op.drop_column('month')

        # Add new unique constraint
        batch_op.create_unique_constraint('uq_budget_start_date', ['start_date'])


def downgrade() -> None:
    with op.batch_alter_table('budgets') as batch_op:
        batch_op.add_column(sa.Column('year', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('month', sa.Integer(), nullable=True))

    # Reverse data migration
    op.execute("""
        UPDATE budgets
        SET year = CAST(STRFTIME('%Y', start_date) AS INTEGER),
            month = CAST(STRFTIME('%m', start_date) AS INTEGER)
    """)

    with op.batch_alter_table('budgets') as batch_op:
        batch_op.alter_column('year', nullable=False)
        batch_op.alter_column('month', nullable=False)
        batch_op.drop_constraint('uq_budget_start_date', type_='unique')
        batch_op.drop_column('start_date')
        batch_op.drop_column('end_date')
        batch_op.create_unique_constraint('uq_budget_year_month', ['year', 'month'])
