"""CRUD for salary allocation buckets.

Spec: docs/superpowers/specs/2026-08-28-salary-allocation-design.md,
sections "Data model", "Validation rules", "Bucket CRUD".
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from datetime import date

from ..models import AllocationBucket, AllocationOverride, Category
from ..schemas import (
    AllocationOverrideOut,
    AllocationOverrideUpsert,
    AllocationBucketBase,
    AllocationBucketCreate,
    AllocationBucketOrderUpdate,
    AllocationBucketOut,
    AllocationBucketUpdate,
)

router = APIRouter(
    prefix="/api/allocation-buckets",
    tags=["allocation-buckets"],
    dependencies=[Depends(require_auth)],
)


def _all_ordered(db: Session) -> list[AllocationBucket]:
    return db.execute(
        select(AllocationBucket).order_by(AllocationBucket.position, AllocationBucket.id)
    ).scalars().all()


def _check_duplicate_name(db: Session, name: str, exclude_id: int | None = None) -> None:
    query = select(AllocationBucket).where(AllocationBucket.name == name)
    if exclude_id is not None:
        query = query.where(AllocationBucket.id != exclude_id)
    if db.execute(query).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A bucket with this name already exists")


def _check_percent_cap(db: Session, *, exclude_id: int | None, adding: float) -> None:
    """Reject a write that would push the active-percent-bucket sum over 100.

    `adding` is the percent value the written bucket will have when it ends
    up active and percent-typed (0.0 when it will be inactive or fixed)."""
    buckets = db.execute(
        select(AllocationBucket).where(
            AllocationBucket.is_active.is_(True),
            AllocationBucket.rule_type == "percent",
        )
    ).scalars().all()
    current = sum(b.value for b in buckets if b.id != exclude_id)
    if current + adding > 100:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Active percentage buckets already total {current:g}%; "
                f"adding {adding:g}% would exceed 100%"
            ),
        )


def _check_category_exists(db: Session, category_id: int) -> None:
    if not db.get(Category, category_id):
        raise HTTPException(status_code=404, detail="Category not found")


def _recompact_positions(db: Session) -> None:
    for i, bucket in enumerate(_all_ordered(db)):
        bucket.position = i


@router.get("", response_model=list[AllocationBucketOut])
def list_buckets(db: Session = Depends(get_db)):
    return _all_ordered(db)


@router.post("", response_model=AllocationBucketOut)
def create_bucket(data: AllocationBucketCreate, db: Session = Depends(get_db)):
    _check_duplicate_name(db, data.name)
    if data.rule_type == "percent":
        _check_percent_cap(db, exclude_id=None, adding=data.value)
    if data.category_id is not None:
        _check_category_exists(db, data.category_id)

    max_position = max((b.position for b in _all_ordered(db)), default=-1)
    bucket = AllocationBucket(
        name=data.name,
        rule_type=data.rule_type,
        value=data.value,
        position=max_position + 1,
        category_id=data.category_id,
    )
    db.add(bucket)
    db.commit()
    db.refresh(bucket)
    return bucket


@router.patch("/{bucket_id}", response_model=AllocationBucketOut)
def update_bucket(bucket_id: int, data: AllocationBucketUpdate, db: Session = Depends(get_db)):
    bucket = db.get(AllocationBucket, bucket_id)
    if not bucket:
        raise HTTPException(status_code=404, detail="Bucket not found")

    fields = data.model_fields_set

    new_name = data.name if "name" in fields else bucket.name
    new_rule_type = data.rule_type if "rule_type" in fields else bucket.rule_type
    new_value = data.value if "value" in fields else bucket.value
    new_active = data.is_active if "is_active" in fields else bucket.is_active

    if "name" in fields:
        _check_duplicate_name(db, new_name, exclude_id=bucket_id)

    # Cross-validate the resulting rule/value pair (the pydantic model can
    # only check whichever half was sent).
    try:
        AllocationBucketBase._validate_rule(new_rule_type, new_value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    adding = new_value if (new_active and new_rule_type == "percent") else 0.0
    _check_percent_cap(db, exclude_id=bucket_id, adding=adding)

    if "category_id" in fields and data.category_id is not None:
        _check_category_exists(db, data.category_id)

    bucket.name = new_name
    bucket.rule_type = new_rule_type
    bucket.value = new_value
    bucket.is_active = new_active
    if "category_id" in fields:
        bucket.category_id = data.category_id  # explicit null clears the link

    db.commit()
    db.refresh(bucket)
    return bucket


@router.delete("/{bucket_id}")
def delete_bucket(bucket_id: int, db: Session = Depends(get_db)):
    bucket = db.get(AllocationBucket, bucket_id)
    if not bucket:
        raise HTTPException(status_code=404, detail="Bucket not found")
    db.query(AllocationOverride).filter(AllocationOverride.bucket_id == bucket_id).delete()
    db.delete(bucket)
    db.flush()
    _recompact_positions(db)
    db.commit()
    return {"ok": True}


@router.put("/order", response_model=list[AllocationBucketOut])
def reorder_buckets(data: AllocationBucketOrderUpdate, db: Session = Depends(get_db)):
    buckets = {b.id: b for b in _all_ordered(db)}
    if set(data.ids) != set(buckets) or len(data.ids) != len(buckets):
        raise HTTPException(
            status_code=400,
            detail="ids must contain every bucket id exactly once",
        )
    for position, bucket_id in enumerate(data.ids):
        buckets[bucket_id].position = position
    db.commit()
    return _all_ordered(db)


@router.get("/overrides", response_model=list[AllocationOverrideOut])
def list_overrides(payday: date, db: Session = Depends(get_db)):
    rows = db.execute(
        select(AllocationOverride)
        .where(AllocationOverride.payday == payday)
        .order_by(AllocationOverride.bucket_id)
    ).scalars().all()
    return [
        AllocationOverrideOut(bucket_id=o.bucket_id, payday=o.payday, value=o.value)
        for o in rows
    ]


@router.put("/{bucket_id}/override", response_model=AllocationOverrideOut)
def upsert_override(bucket_id: int, data: AllocationOverrideUpsert, db: Session = Depends(get_db)):
    """Set a one-payday value for a bucket. The default is untouched; the
    override applies to exactly this payday and expires with it."""
    bucket = db.get(AllocationBucket, bucket_id)
    if not bucket:
        raise HTTPException(status_code=404, detail="Bucket not found")
    # Unlike bucket defaults, an override of 0 is valid: it skips the
    # bucket for exactly this payday.
    if data.value < 0:
        raise HTTPException(status_code=422, detail="Override value must be 0 or more")
    if bucket.rule_type == "percent" and data.value > 100:
        raise HTTPException(status_code=422, detail="Percentage must be at most 100")

    if bucket.rule_type == "percent":
        # Effective percent sum for THIS payday must stay within 100.
        overrides = {
            o.bucket_id: o.value
            for o in db.execute(
                select(AllocationOverride).where(AllocationOverride.payday == data.payday)
            ).scalars().all()
        }
        overrides[bucket_id] = data.value
        active_percent = db.execute(
            select(AllocationBucket).where(
                AllocationBucket.is_active.is_(True),
                AllocationBucket.rule_type == "percent",
            )
        ).scalars().all()
        total = sum(overrides.get(b.id, b.value) for b in active_percent)
        if total > 100:
            raise HTTPException(
                status_code=409,
                detail=f"Percentage buckets would total {total:g}% on {data.payday}; the maximum is 100%",
            )

    existing = db.execute(
        select(AllocationOverride).where(
            AllocationOverride.bucket_id == bucket_id,
            AllocationOverride.payday == data.payday,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.value = data.value
    else:
        db.add(AllocationOverride(bucket_id=bucket_id, payday=data.payday, value=data.value))
    db.commit()
    return AllocationOverrideOut(bucket_id=bucket_id, payday=data.payday, value=data.value)


@router.delete("/{bucket_id}/override")
def delete_override(bucket_id: int, payday: date, db: Session = Depends(get_db)):
    db.query(AllocationOverride).filter(
        AllocationOverride.bucket_id == bucket_id,
        AllocationOverride.payday == payday,
    ).delete()
    db.commit()
    return {"ok": True}
