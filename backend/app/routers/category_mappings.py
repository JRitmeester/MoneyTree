from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Category, CategoryMapping, Transaction
from ..schemas import CategoryMappingCreate, CategoryMappingOut

router = APIRouter(prefix="/api/category-mappings", tags=["category_mappings"])


@router.get("", response_model=list[CategoryMappingOut])
def list_mappings(db: Session = Depends(get_db)):
    """List all bank category mappings."""
    mappings = db.execute(select(CategoryMapping)).scalars().all()
    return [
        CategoryMappingOut(
            id=m.id,
            bank_category=m.bank_category,
            category_id=m.category_id,
            category_name=m.category.name,
        )
        for m in mappings
    ]


@router.post("", response_model=CategoryMappingOut, status_code=201)
def create_mapping(data: CategoryMappingCreate, db: Session = Depends(get_db)):
    """Create a bank category mapping."""
    existing = db.execute(
        select(CategoryMapping).where(
            CategoryMapping.bank_category == data.bank_category
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Mapping for '{data.bank_category}' already exists",
        )

    cat = db.get(Category, data.category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    mapping = CategoryMapping(
        bank_category=data.bank_category, category_id=data.category_id
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return CategoryMappingOut(
        id=mapping.id,
        bank_category=mapping.bank_category,
        category_id=mapping.category_id,
        category_name=cat.name,
    )


@router.put("/{mapping_id}", response_model=CategoryMappingOut)
def update_mapping(
    mapping_id: int, data: CategoryMappingCreate, db: Session = Depends(get_db)
):
    """Update a bank category mapping."""
    mapping = db.get(CategoryMapping, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    cat = db.get(Category, data.category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    mapping.bank_category = data.bank_category
    mapping.category_id = data.category_id
    db.commit()
    db.refresh(mapping)
    return CategoryMappingOut(
        id=mapping.id,
        bank_category=mapping.bank_category,
        category_id=mapping.category_id,
        category_name=cat.name,
    )


@router.delete("/{mapping_id}")
def delete_mapping(mapping_id: int, db: Session = Depends(get_db)):
    """Delete a bank category mapping."""
    mapping = db.get(CategoryMapping, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    db.delete(mapping)
    db.commit()
    return {"ok": True}


@router.get("/unmapped", response_model=list[str])
def get_unmapped(db: Session = Depends(get_db)):
    """List bank categories that have no mapping."""
    # Get all distinct bank categories from transactions
    all_bank_cats = db.execute(
        select(Transaction.categorie).distinct()
    ).scalars().all()

    # Get all mapped bank categories
    mapped_cats = db.execute(
        select(CategoryMapping.bank_category)
    ).scalars().all()
    mapped_set = set(mapped_cats)

    return sorted(c for c in all_bank_cats if c and c not in mapped_set)
