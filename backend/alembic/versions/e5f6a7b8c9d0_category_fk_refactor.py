"""category_fk_refactor

Replace LineItem.category string and add Transaction.category_id FK.
- Adds line_items.category_id (FK → categories)
- Adds transactions.category_id (FK → categories)
- Backfills both from existing string data
- Drops line_items.category string column
- Drops categories.is_bank_category column (no longer used)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _resolve_category_string(cat_str: str, name_to_id: dict, id_to_parent: dict) -> int | None:
    """Inline resolver: maps a category string (possibly 'Parent > Child') to a category ID."""
    if not cat_str:
        return None

    cat_id = None

    if ">" in cat_str:
        parts = [p.strip() for p in cat_str.split(">") if p.strip()]
        parent_id = None
        resolved = True
        for part in parts:
            part_lower = part.lower()
            found_id = None
            # Find category with this name under parent_id
            for cid, (name, pid) in id_to_parent.items():
                if name.lower() == part_lower and pid == parent_id:
                    found_id = cid
                    break
            if found_id is None:
                # Try without parent constraint
                found_id = name_to_id.get(part_lower)
            if found_id is None:
                resolved = False
                break
            parent_id = found_id
        if resolved and parent_id is not None:
            cat_id = parent_id

    if cat_id is None:
        cat_id = name_to_id.get(cat_str.lower())

    return cat_id


def upgrade() -> None:
    conn = op.get_bind()

    # --- 1. Add category_id to transactions ---
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.add_column(sa.Column('category_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_transactions_category_id',
            'categories', ['category_id'], ['id']
        )

    # --- 2. Add category_id to line_items ---
    with op.batch_alter_table('line_items') as batch_op:
        batch_op.add_column(sa.Column('category_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_line_items_category_id',
            'categories', ['category_id'], ['id']
        )

    # --- 3. Backfill transactions.category_id from CategoryMapping ---
    conn.execute(sa.text("""
        UPDATE transactions
        SET category_id = (
            SELECT cm.category_id
            FROM category_mappings cm
            WHERE cm.bank_category = transactions.categorie
            LIMIT 1
        )
        WHERE EXISTS (
            SELECT 1 FROM category_mappings cm
            WHERE cm.bank_category = transactions.categorie
        )
    """))

    # --- 4. Backfill line_items.category_id from string ---
    # Build lookup structures from current categories table
    rows = conn.execute(sa.text("SELECT id, name, parent_id FROM categories")).fetchall()
    name_to_id: dict[str, int] = {}
    id_to_parent: dict[int, tuple] = {}  # id -> (name, parent_id)
    for row in rows:
        cid, name, parent_id = row
        name_to_id[name.lower()] = cid
        id_to_parent[cid] = (name, parent_id)

    # Fetch all line items with a category string
    li_rows = conn.execute(sa.text(
        "SELECT id, category FROM line_items WHERE category IS NOT NULL AND category != ''"
    )).fetchall()

    for li_id, cat_str in li_rows:
        resolved_id = _resolve_category_string(cat_str, name_to_id, id_to_parent)
        if resolved_id is not None:
            conn.execute(
                sa.text("UPDATE line_items SET category_id = :cid WHERE id = :lid"),
                {"cid": resolved_id, "lid": li_id}
            )

    # --- 5. Drop line_items.category string column ---
    with op.batch_alter_table('line_items') as batch_op:
        batch_op.drop_column('category')

    # --- 6. Drop categories.is_bank_category column (no longer used) ---
    with op.batch_alter_table('categories') as batch_op:
        batch_op.drop_column('is_bank_category')


def downgrade() -> None:
    # Restore is_bank_category on categories
    with op.batch_alter_table('categories') as batch_op:
        batch_op.add_column(sa.Column('is_bank_category', sa.Boolean(), nullable=False, server_default='0'))

    # Restore line_items.category string column (nullable; original data is lost)
    with op.batch_alter_table('line_items') as batch_op:
        batch_op.drop_constraint('fk_line_items_category_id', type_='foreignkey')
        batch_op.drop_column('category_id')
        batch_op.add_column(sa.Column('category', sa.String(100), nullable=True))

    # Drop transactions.category_id
    with op.batch_alter_table('transactions') as batch_op:
        batch_op.drop_constraint('fk_transactions_category_id', type_='foreignkey')
        batch_op.drop_column('category_id')
