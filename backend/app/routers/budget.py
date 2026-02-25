from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Budget, BudgetLine, Category
from ..schemas import (
    BudgetCreate,
    BudgetLineOut,
    BudgetOut,
    BudgetSummary,
    BudgetUpdate,
)

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


def _budget_to_out(budget: Budget) -> BudgetOut:
    lines = [
        BudgetLineOut(
            id=line.id,
            category_id=line.category_id,
            category_name=line.category.name,
            category_type=line.category.category_type,
            amount=line.amount,
        )
        for line in budget.lines
    ]
    return BudgetOut(
        id=budget.id,
        year=budget.year,
        month=budget.month,
        lines=lines,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


@router.get("", response_model=list[BudgetSummary])
def list_budgets(db: Session = Depends(get_db)):
    """List all budgets (summary view)."""
    budgets = db.execute(
        select(Budget).order_by(Budget.year.desc(), Budget.month.desc())
    ).scalars().all()
    return [
        BudgetSummary(
            id=b.id,
            year=b.year,
            month=b.month,
            line_count=len(b.lines),
            created_at=b.created_at,
            updated_at=b.updated_at,
        )
        for b in budgets
    ]


@router.get("/{year}/{month}", response_model=BudgetOut)
def get_budget(year: int, month: int, db: Session = Depends(get_db)):
    """Get a budget for a specific month with all lines."""
    budget = db.execute(
        select(Budget).where(Budget.year == year, Budget.month == month)
    ).scalar_one_or_none()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    return _budget_to_out(budget)


@router.post("", response_model=BudgetOut, status_code=201)
def create_budget(data: BudgetCreate, db: Session = Depends(get_db)):
    """Create a budget for a month with lines."""
    existing = db.execute(
        select(Budget).where(Budget.year == data.year, Budget.month == data.month)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Budget already exists for this month")

    budget = Budget(year=data.year, month=data.month)
    db.add(budget)
    db.flush()

    for line_data in data.lines:
        cat = db.get(Category, line_data.category_id)
        if not cat:
            raise HTTPException(
                status_code=404,
                detail=f"Category {line_data.category_id} not found",
            )
        db.add(BudgetLine(
            budget_id=budget.id,
            category_id=line_data.category_id,
            amount=line_data.amount,
        ))

    db.commit()
    db.refresh(budget)
    return _budget_to_out(budget)


@router.put("/{year}/{month}", response_model=BudgetOut)
def update_budget(year: int, month: int, data: BudgetUpdate, db: Session = Depends(get_db)):
    """Update a budget (replaces all lines)."""
    budget = db.execute(
        select(Budget).where(Budget.year == year, Budget.month == month)
    ).scalar_one_or_none()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    # Delete existing lines
    for line in list(budget.lines):
        db.delete(line)
    db.flush()

    # Add new lines
    for line_data in data.lines:
        cat = db.get(Category, line_data.category_id)
        if not cat:
            raise HTTPException(
                status_code=404,
                detail=f"Category {line_data.category_id} not found",
            )
        db.add(BudgetLine(
            budget_id=budget.id,
            category_id=line_data.category_id,
            amount=line_data.amount,
        ))

    db.commit()
    db.refresh(budget)
    return _budget_to_out(budget)


@router.delete("/{year}/{month}")
def delete_budget(year: int, month: int, db: Session = Depends(get_db)):
    """Delete a budget."""
    budget = db.execute(
        select(Budget).where(Budget.year == year, Budget.month == month)
    ).scalar_one_or_none()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    db.delete(budget)
    db.commit()
    return {"ok": True}


@router.post("/{year}/{month}/copy-from/{src_year}/{src_month}", response_model=BudgetOut, status_code=201)
def copy_budget(
    year: int, month: int, src_year: int, src_month: int,
    db: Session = Depends(get_db),
):
    """Copy a budget from another month."""
    existing = db.execute(
        select(Budget).where(Budget.year == year, Budget.month == month)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Budget already exists for target month")

    source = db.execute(
        select(Budget).where(Budget.year == src_year, Budget.month == src_month)
    ).scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source budget not found")

    budget = Budget(year=year, month=month)
    db.add(budget)
    db.flush()

    for line in source.lines:
        db.add(BudgetLine(
            budget_id=budget.id,
            category_id=line.category_id,
            amount=line.amount,
        ))

    db.commit()
    db.refresh(budget)
    return _budget_to_out(budget)
