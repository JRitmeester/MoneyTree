from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Budget, BudgetLine, BudgetTemplate, Category
from ..schemas import (
    BudgetLineOut,
    BudgetOut,
    BudgetSummary,
    BudgetUpdate,
)

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


def _create_from_template(db: Session, year: int, month: int) -> Budget:
    """Create a monthly budget from the template."""
    budget = Budget(year=year, month=month)
    db.add(budget)
    db.flush()

    templates = db.execute(select(BudgetTemplate)).scalars().all()
    for t in templates:
        db.add(BudgetLine(
            budget_id=budget.id,
            category_id=t.category_id,
            amount=t.amount,
        ))

    db.commit()
    db.refresh(budget)
    return budget


def _budget_to_out(budget: Budget, db: Session) -> BudgetOut:
    """Convert a budget to output format with template-awareness."""
    # Load template amounts for comparison
    templates = db.execute(select(BudgetTemplate)).scalars().all()
    template_by_cat = {t.category_id: t.amount for t in templates}

    lines = []
    for line in budget.lines:
        cat = line.category
        template_amount = template_by_cat.get(line.category_id, 0.0)
        is_overridden = abs(line.amount - template_amount) > 0.001

        lines.append(BudgetLineOut(
            id=line.id,
            category_id=line.category_id,
            category_name=cat.name,
            category_type=cat.category_type,
            is_fixed=cat.is_fixed,
            amount=line.amount,
            is_overridden=is_overridden,
            template_amount=template_amount,
        ))

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
    """Get a budget for a specific month. Auto-creates from template if not exists."""
    budget = db.execute(
        select(Budget).where(Budget.year == year, Budget.month == month)
    ).scalar_one_or_none()

    if not budget:
        # Check if template has any lines
        template_count = db.execute(select(BudgetTemplate)).scalars().all()
        if not template_count:
            raise HTTPException(status_code=404, detail="No budget template configured")
        budget = _create_from_template(db, year, month)

    return _budget_to_out(budget, db)


@router.put("/{year}/{month}", response_model=BudgetOut)
def update_budget(
    year: int,
    month: int,
    data: BudgetUpdate,
    update_template: bool = False,
    db: Session = Depends(get_db),
):
    """Update a budget (replaces all lines). Creates if not exists. Optionally updates template too."""
    budget = db.execute(
        select(Budget).where(Budget.year == year, Budget.month == month)
    ).scalar_one_or_none()

    if not budget:
        budget = Budget(year=year, month=month)
        db.add(budget)
        db.flush()
    else:
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

    # Optionally update template
    if update_template:
        existing_templates = db.execute(select(BudgetTemplate)).scalars().all()
        for t in existing_templates:
            db.delete(t)
        db.flush()
        for line_data in data.lines:
            db.add(BudgetTemplate(
                category_id=line_data.category_id,
                amount=line_data.amount,
            ))

    db.commit()
    db.refresh(budget)
    return _budget_to_out(budget, db)


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
