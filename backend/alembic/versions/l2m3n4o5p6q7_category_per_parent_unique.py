"""category_per_parent_unique

Replace the global unique constraint on categories.name with a composite
unique constraint on (parent_id, name), so two categories can share a name
as long as they have different parents (e.g. "Overig" under both "Living"
and "Travel").

SQLite implements a Column(unique=True) constraint as an anonymous
autoindex, which cannot be dropped in place (and is not reliably reflected
by name for `batch_op.drop_constraint`). We therefore rebuild the table by
hand: create the new table with the desired constraint, copy rows across
verbatim (ids preserved so every other table's category_id FK stays
valid), drop the old table, then rename the new one into place. SQLite's
ALTER TABLE RENAME TO fixes up the self-referential parent_id FK
automatically.

NOTE: SQLite treats NULL as distinct from every other value in a unique
index, so root-level categories (parent_id IS NULL) are NOT constrained by
this composite unique index. Root-level sibling uniqueness is enforced in
the application layer (backend/app/routers/categories.py).

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-08-27 23:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'l2m3n4o5p6q7'
down_revision: Union[str, None] = 'k1l2m3n4o5p6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The FK below points at 'categories' (the final table name), not at
    # 'categories_new': a table named 'categories' still exists (the old
    # one, about to be dropped) when this table is created, and SQLite
    # doesn't validate the reference target at CREATE TABLE time. Once we
    # drop the old table and rename this one into place, the stored FK text
    # correctly self-references the renamed table.
    op.create_table(
        'categories_new',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('categories.id'), nullable=True),
        sa.Column('is_fixed', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('category_type', sa.String(length=10), nullable=False, server_default='expense'),
        sa.UniqueConstraint('parent_id', 'name', name='uq_category_parent_name'),
    )
    op.execute("""
        INSERT INTO categories_new (id, name, parent_id, is_fixed, category_type)
        SELECT id, name, parent_id, is_fixed, category_type FROM categories
    """)
    op.drop_table('categories')
    op.rename_table('categories_new', 'categories')


def downgrade() -> None:
    op.create_table(
        'categories_old',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=100), unique=True, nullable=False),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('categories.id'), nullable=True),
        sa.Column('is_fixed', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('category_type', sa.String(length=10), nullable=False, server_default='expense'),
    )
    # Best-effort: if per-parent duplicate names now exist, this insert will
    # fail on the restored global-unique constraint. That is an accepted
    # limitation of downgrading past this migration.
    op.execute("""
        INSERT INTO categories_old (id, name, parent_id, is_fixed, category_type)
        SELECT id, name, parent_id, is_fixed, category_type FROM categories
    """)
    op.drop_table('categories')
    op.rename_table('categories_old', 'categories')
