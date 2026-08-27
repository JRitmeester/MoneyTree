from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import (
    BudgetLine, BudgetTemplate, Category, CategoryMapping, LineItem, Transaction,
)
from ..schemas import CategoryCreate, CategoryMergeCounts, CategoryOut, CategoryUpdate
from ..services.category_merge import apply_category_merge, count_category_references, is_descendant
from ..services.category_paths import full_category_path
from ..services.sync_events import (
    EVENT_CATEGORY_DELETE, EVENT_CATEGORY_MERGE, EVENT_CATEGORY_RENAME, EVENT_CATEGORY_UPDATE,
    record_event,
)

router = APIRouter(prefix="/api/categories", tags=["categories"], dependencies=[Depends(require_auth)])


def _sibling_conflict_message(name: str, parent_id: int | None, db: Session) -> str:
    if parent_id is None:
        return f'A category named "{name}" already exists at the top level'
    parent = db.get(Category, parent_id)
    parent_label = parent.name if parent else "Unknown"
    return f'A category named "{name}" already exists under "{parent_label}"'


def _find_sibling(db: Session, name: str, parent_id: int | None, exclude_id: int | None = None) -> Category | None:
    """Find an existing sibling with this name under this parent.

    Enforces the app-layer half of sibling uniqueness: the DB's composite
    unique constraint on (parent_id, name) doesn't catch root-level
    (parent_id IS NULL) duplicates, because SQLite treats NULL as distinct
    from every other value in a unique index.
    """
    stmt = select(Category).where(Category.name == name)
    stmt = stmt.where(Category.parent_id.is_(None)) if parent_id is None else stmt.where(Category.parent_id == parent_id)
    if exclude_id is not None:
        stmt = stmt.where(Category.id != exclude_id)
    return db.execute(stmt).scalar_one_or_none()


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    """Get all categories as a flat list (children populated)."""
    top_level = db.execute(
        select(Category).where(Category.parent_id.is_(None)).order_by(Category.name)
    ).scalars().all()
    return top_level


@router.post("", response_model=CategoryOut)
def create_category(data: CategoryCreate, db: Session = Depends(get_db)):
    """Create a new category (optionally as child of another).

    Names are unique per parent, not globally: two categories can share a
    name as long as they have different parents.
    """
    if _find_sibling(db, data.name, data.parent_id) is not None:
        raise HTTPException(
            status_code=409,
            detail=_sibling_conflict_message(data.name, data.parent_id, db),
        )

    if data.parent_id:
        parent = db.get(Category, data.parent_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Parent category not found")

    cat = Category(
        name=data.name,
        parent_id=data.parent_id,
        category_type=data.category_type,
        is_fixed=data.is_fixed,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(category_id: int, data: CategoryUpdate, db: Session = Depends(get_db)):
    """Rename a category and/or change its attributes.

    Only fields present in the request body are applied; omitted fields keep
    their current value (e.g. renaming does not reset is_fixed/category_type).
    """
    cat = db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    fields = data.model_dump(exclude_unset=True)

    old_name = cat.name
    new_parent_id = fields.get("parent_id", cat.parent_id)
    new_category_type = fields.get("category_type", cat.category_type)
    new_is_fixed = fields.get("is_fixed", cat.is_fixed)
    new_name = fields.get("name", cat.name)

    attr_changed = (
        new_category_type != cat.category_type
        or new_is_fixed != cat.is_fixed
        or new_parent_id != cat.parent_id
    )
    name_or_parent_changed = new_name != old_name or new_parent_id != cat.parent_id

    if name_or_parent_changed:
        conflict = _find_sibling(db, new_name, new_parent_id, exclude_id=cat.id)
        if conflict is not None:
            raise HTTPException(
                status_code=409,
                detail=_sibling_conflict_message(new_name, new_parent_id, db),
            )

    # Snapshot the id->Category map before mutating anything, to compute the
    # pre-change path. The post-change path is built from the *final*
    # parent's (unmutated) path plus the new name, since the parent itself
    # isn't affected by this rename.
    cat_by_id = {c.id: c for c in db.execute(select(Category)).scalars().all()}
    old_path = full_category_path(cat.id, cat_by_id)

    if new_name != old_name:
        new_parent_path = full_category_path(new_parent_id, cat_by_id) if new_parent_id else None
        new_path = f"{new_parent_path} > {new_name}" if new_parent_path else new_name
        record_event(db, EVENT_CATEGORY_RENAME, {
            "old_name": old_name, "new_name": new_name,
            "old_path": old_path, "new_path": new_path,
        })

    cat.name = new_name
    if "parent_id" in fields:
        cat.parent_id = fields["parent_id"]
    cat.category_type = new_category_type
    cat.is_fixed = new_is_fixed

    if attr_changed:
        new_parent = db.get(Category, cat.parent_id) if cat.parent_id else None
        record_event(db, EVENT_CATEGORY_UPDATE, {
            "name": cat.name,
            "parent_name": new_parent.name if new_parent else None,
            "is_fixed": cat.is_fixed,
            "category_type": cat.category_type,
        })

    db.commit()
    db.refresh(cat)
    return cat


def _count(db: Session, model, category_id: int) -> int:
    return db.execute(
        select(func.count()).select_from(model).where(model.category_id == category_id)
    ).scalar_one()


@router.delete("/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    """Delete a category. Must have no children and no references left."""
    cat = db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    if cat.children:
        raise HTTPException(status_code=409, detail="Category has children, delete them first")

    reference_counts = [
        (_count(db, Transaction, category_id), "transaction"),
        (_count(db, LineItem, category_id), "line item"),
        (_count(db, BudgetLine, category_id), "budget line"),
        (_count(db, BudgetTemplate, category_id), "budget template"),
        (_count(db, CategoryMapping, category_id), "category mapping"),
    ]
    parts = [
        f"{count} {label}{'s' if count != 1 else ''}"
        for count, label in reference_counts
        if count > 0
    ]
    if parts:
        raise HTTPException(
            status_code=409,
            detail=f"Category is in use: {', '.join(parts)}. Reassign them first.",
        )

    cat_by_id = {c.id: c for c in db.execute(select(Category)).scalars().all()}
    path = full_category_path(cat.id, cat_by_id)
    record_event(db, EVENT_CATEGORY_DELETE, {"name": cat.name, "path": path})
    db.delete(cat)
    db.commit()
    return {"ok": True}


@router.post("/{source_id}/merge-into/{target_id}", response_model=CategoryMergeCounts)
def merge_category(
    source_id: int, target_id: int, dry_run: bool = False, db: Session = Depends(get_db)
):
    """Merge source category into target: re-point all references, summing
    budget lines/templates on clash, re-parent children, then delete source.

    With ?dry_run=true, returns the counts that would be re-pointed without
    mutating anything or recording a sync event.
    """
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="Cannot merge a category into itself")

    source = db.get(Category, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source category not found")

    target = db.get(Category, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target category not found")

    if is_descendant(db, source_id, target_id):
        raise HTTPException(
            status_code=400,
            detail="Target category cannot be a descendant of the source category",
        )

    counts = count_category_references(db, source_id)

    if dry_run:
        return counts

    # Re-parenting source's children under target could collide with a
    # same-named child target already has (impossible before per-parent
    # names, now possible and would otherwise hit the DB unique constraint).
    # Query by column rather than via the `children` relationship: touching
    # that ORM collection here would cache it, and SQLAlchemy's default
    # one-to-many delete behavior would later null out the (already
    # raw-SQL-reparented) children's parent_id when `source` is deleted.
    target_child_names = set(db.execute(
        select(Category.name).where(Category.parent_id == target.id)
    ).scalars().all())
    source_child_names = db.execute(
        select(Category.name).where(Category.parent_id == source.id)
    ).scalars().all()
    clashing = [name for name in source_child_names if name in target_child_names]
    if clashing:
        raise HTTPException(
            status_code=409,
            detail=_sibling_conflict_message(clashing[0], target.id, db),
        )

    source_name, target_name = source.name, target.name
    cat_by_id = {c.id: c for c in db.execute(select(Category)).scalars().all()}
    source_path = full_category_path(source.id, cat_by_id)
    target_path = full_category_path(target.id, cat_by_id)
    apply_category_merge(db, source, target)
    record_event(db, EVENT_CATEGORY_MERGE, {
        "source_name": source_name, "target_name": target_name,
        "source_path": source_path, "target_path": target_path,
    })
    db.commit()
    return counts
