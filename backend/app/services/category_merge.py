"""Category merge logic shared by the merge endpoint and sync import.

Re-points every reference from a source category to a target category. When
both categories already have a row in the same unique-constrained table
(budget lines per budget, budget templates per category), the source amount
is summed into the target row and the source row is deleted, so the unique
constraint is never violated.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import BudgetLine, BudgetTemplate, Category, CategoryMapping, LineItem, Transaction


def _count(db: Session, model, value: int, column: str = "category_id") -> int:
    col = getattr(model, column)
    return db.execute(
        select(func.count()).select_from(model).where(col == value)
    ).scalar_one()


def is_descendant(db: Session, ancestor_id: int, node_id: int) -> bool:
    """True if node_id is a descendant of ancestor_id (walking up the parent chain)."""
    current = db.get(Category, node_id)
    while current is not None and current.parent_id is not None:
        if current.parent_id == ancestor_id:
            return True
        current = db.get(Category, current.parent_id)
    return False


def count_category_references(db: Session, category_id: int) -> dict:
    """Counts of rows that would be re-pointed by merging category_id away."""
    return {
        "transactions": _count(db, Transaction, category_id),
        "line_items": _count(db, LineItem, category_id),
        "budget_lines": _count(db, BudgetLine, category_id),
        "budget_templates": _count(db, BudgetTemplate, category_id),
        "category_mappings": _count(db, CategoryMapping, category_id),
        "children": _count(db, Category, category_id, column="parent_id"),
    }


def apply_category_merge(db: Session, source: Category, target: Category) -> None:
    """Re-point all references from source to target, then delete source.

    Does not commit and does not record a sync event; callers own the
    surrounding transaction and event recording.
    """
    source_id, target_id = source.id, target.id

    # Defensive: if `source.children` was already loaded by earlier code in
    # this session (e.g. a caller checking for a sibling-name clash before
    # merging), expire it now. SQLAlchemy's default one-to-many delete
    # behavior nulls out the FK of any *loaded* children collection when the
    # parent is deleted below; the raw bulk UPDATE further down already
    # reparents them correctly, so a stale cached collection must not be
    # allowed to clobber that with a redundant (and wrong) null-out.
    db.expire(source, ["children"])

    db.execute(
        Transaction.__table__.update()
        .where(Transaction.category_id == source_id)
        .values(category_id=target_id)
    )
    db.execute(
        LineItem.__table__.update()
        .where(LineItem.category_id == source_id)
        .values(category_id=target_id)
    )
    db.execute(
        CategoryMapping.__table__.update()
        .where(CategoryMapping.category_id == source_id)
        .values(category_id=target_id)
    )
    db.execute(
        Category.__table__.update()
        .where(Category.parent_id == source_id)
        .values(parent_id=target_id)
    )

    source_lines = db.execute(
        select(BudgetLine).where(BudgetLine.category_id == source_id)
    ).scalars().all()
    for line in source_lines:
        target_line = db.execute(
            select(BudgetLine).where(
                BudgetLine.budget_id == line.budget_id,
                BudgetLine.category_id == target_id,
            )
        ).scalar_one_or_none()
        if target_line is not None:
            target_line.amount += line.amount
            db.delete(line)
        else:
            line.category_id = target_id

    source_template = db.execute(
        select(BudgetTemplate).where(BudgetTemplate.category_id == source_id)
    ).scalar_one_or_none()
    if source_template is not None:
        target_template = db.execute(
            select(BudgetTemplate).where(BudgetTemplate.category_id == target_id)
        ).scalar_one_or_none()
        if target_template is not None:
            target_template.amount += source_template.amount
            db.delete(source_template)
        else:
            source_template.category_id = target_id

    db.flush()
    db.delete(source)
