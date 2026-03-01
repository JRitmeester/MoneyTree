from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Category
from ..schemas import CategoryCreate, CategoryOut

router = APIRouter(prefix="/api/categories", tags=["categories"])


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
        is_bank_category=False,
        category_type=data.category_type,
        is_fixed=data.is_fixed,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(category_id: int, data: CategoryCreate, db: Session = Depends(get_db)):
    """Rename a category."""
    cat = db.get(Category, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    cat.name = data.name
    if data.parent_id is not None:
        cat.parent_id = data.parent_id
    cat.category_type = data.category_type
    cat.is_fixed = data.is_fixed
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

    db.delete(cat)
    db.commit()
    return {"ok": True}
