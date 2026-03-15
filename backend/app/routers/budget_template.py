from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import BudgetTemplate, Category
from ..schemas import BudgetTemplateLineCreate, BudgetTemplateLineOut, BudgetTemplateOut

router = APIRouter(prefix="/api/budget-template", tags=["budget-template"], dependencies=[Depends(require_auth)])


def _build_template_response(db: Session) -> BudgetTemplateOut:
    templates = db.execute(
        select(BudgetTemplate).order_by(BudgetTemplate.id)
    ).scalars().all()

    lines = []
    total_income = 0.0
    total_fixed_expenses = 0.0
    total_savings = 0.0
    total_flexible_expenses = 0.0

    for t in templates:
        cat = t.category
        line = BudgetTemplateLineOut(
            id=t.id,
            category_id=t.category_id,
            category_name=cat.name,
            category_type=cat.category_type,
            is_fixed=cat.is_fixed,
            amount=t.amount,
        )
        lines.append(line)

        if cat.category_type == "income":
            total_income += t.amount
        elif cat.category_type == "savings":
            total_savings += t.amount
        elif cat.is_fixed:
            total_fixed_expenses += t.amount
        else:
            total_flexible_expenses += t.amount

    discretionary = total_income - total_fixed_expenses - total_savings
    unallocated = discretionary - total_flexible_expenses

    return BudgetTemplateOut(
        lines=lines,
        total_income=total_income,
        total_fixed_expenses=total_fixed_expenses,
        discretionary=discretionary,
        total_flexible_expenses=total_flexible_expenses,
        unallocated=unallocated,
    )


@router.get("", response_model=BudgetTemplateOut)
def get_template(db: Session = Depends(get_db)):
    """Get the budget template with all lines and computed totals."""
    return _build_template_response(db)


@router.put("", response_model=BudgetTemplateOut)
def replace_template(
    lines: list[BudgetTemplateLineCreate],
    db: Session = Depends(get_db),
):
    """Replace all template lines."""
    # Validate all categories exist
    for line_data in lines:
        cat = db.get(Category, line_data.category_id)
        if not cat:
            raise HTTPException(
                status_code=404,
                detail=f"Category {line_data.category_id} not found",
            )

    # Delete existing template
    existing = db.execute(select(BudgetTemplate)).scalars().all()
    for t in existing:
        db.delete(t)
    db.flush()

    # Create new lines
    for line_data in lines:
        db.add(BudgetTemplate(
            category_id=line_data.category_id,
            amount=line_data.amount,
        ))

    db.commit()
    return _build_template_response(db)


@router.patch("/{line_id}", response_model=BudgetTemplateOut)
def update_template_line(
    line_id: int,
    data: BudgetTemplateLineCreate,
    db: Session = Depends(get_db),
):
    """Update a single template line's amount."""
    template_line = db.get(BudgetTemplate, line_id)
    if not template_line:
        raise HTTPException(status_code=404, detail="Template line not found")

    template_line.amount = data.amount
    db.commit()
    return _build_template_response(db)
