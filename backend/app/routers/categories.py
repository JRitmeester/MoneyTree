from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import Category
from ..schemas import CategoryCreate, CategoryOut, CategoryUpdate
from ..services.sync_events import (
    EVENT_CATEGORY_DELETE, EVENT_CATEGORY_RENAME, EVENT_CATEGORY_UPDATE,
    record_event,
)

router = APIRouter(prefix="/api/categories", tags=["categories"], dependencies=[Depends(require_auth)])


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    """Get all categories as a flat list (children populated)."""
    top_level = db.execute(
        select(Category).where(Category.parent_id.is_(None)).order_by(Category.name)
    ).scalars().all()
    return top_level


@router.post("", response_model=CategoryOut)
def create_category(data: CategoryCreate, db: Session = Depends(get_db)):
    """Create a new category (optionally as child of another)."""
    existing = db.execute(
        select(Category).where(Category.name == data.name)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Category already exists")

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

    if new_name != old_name:
        record_event(db, EVENT_CATEGORY_RENAME, {
            "old_name": old_name, "new_name": new_name,
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


@router.delete("/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    """Delete a category (must have no children)."""
    cat = db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    if cat.children:
        raise HTTPException(status_code=409, detail="Category has children, delete them first")

    record_event(db, EVENT_CATEGORY_DELETE, {"name": cat.name})
    db.delete(cat)
    db.commit()
    return {"ok": True}
