from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import Budget, BudgetLine, BudgetTemplate, Category, LineItem, Receipt, Transaction
from ..schemas import (
    BudgetCreate,
    BudgetLineOut,
    BudgetOut,
    BudgetPatch,
    BudgetSummary,
    BudgetUpdate,
)

router = APIRouter(prefix="/api/budgets", tags=["budgets"], dependencies=[Depends(require_auth)])


def _create_from_template(db: Session, start_date: date, end_date: date) -> Budget:
    """Create a budget period from the template."""
    budget = Budget(start_date=start_date, end_date=end_date)
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


def _savings_balances(db: Session) -> dict[int, float]:
    """Calculate running balance for all savings categories.

    Balance = sum(budgeted across all periods) - sum(actual spending all time).
    """
    savings_cat_ids = set(
        db.execute(
            select(Category.id).where(Category.category_type == "savings")
        ).scalars().all()
    )
    if not savings_cat_ids:
        return {}

    # Total budgeted per savings category across all budget periods
    budgeted_rows = db.execute(
        select(BudgetLine.category_id, func.sum(BudgetLine.amount))
        .where(BudgetLine.category_id.in_(savings_cat_ids))
        .group_by(BudgetLine.category_id)
    ).all()
    budgeted = {cat_id: total or 0.0 for cat_id, total in budgeted_rows}

    # Total spent: direct transactions (no receipt)
    direct_rows = db.execute(
        select(Transaction.category_id, func.sum(func.abs(Transaction.bedrag)))
        .where(
            Transaction.category_id.in_(savings_cat_ids),
            Transaction.bedrag < 0,
            ~select(Receipt.id).where(Receipt.transaction_id == Transaction.id).exists(),
        )
        .group_by(Transaction.category_id)
    ).all()

    # Total spent: line items from receipts
    li_rows = db.execute(
        select(LineItem.category_id, func.sum(LineItem.amount * LineItem.quantity))
        .join(Receipt)
        .join(Transaction)
        .where(
            LineItem.category_id.in_(savings_cat_ids),
            Transaction.bedrag < 0,
        )
        .group_by(LineItem.category_id)
    ).all()

    spent: dict[int, float] = {}
    for cat_id, total in list(direct_rows) + list(li_rows):
        spent[cat_id] = spent.get(cat_id, 0.0) + (total or 0.0)

    return {
        cat_id: round(budgeted.get(cat_id, 0.0) - spent.get(cat_id, 0.0), 2)
        for cat_id in savings_cat_ids
    }


def _budget_to_out(budget: Budget, db: Session) -> BudgetOut:
    """Convert a budget to output format with template-awareness."""
    templates = db.execute(select(BudgetTemplate)).scalars().all()
    template_by_cat = {t.category_id: t.amount for t in templates}
    balances = _savings_balances(db)

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
            balance=balances.get(line.category_id, 0.0),
        ))

    return BudgetOut(
        id=budget.id,
        start_date=budget.start_date,
        end_date=budget.end_date,
        lines=lines,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


def _check_overlap(db: Session, start_date: date, end_date: date, exclude_id: int | None = None):
    """Raise 409 if the given date range overlaps an existing budget."""
    query = select(Budget).where(
        Budget.start_date < end_date,
        Budget.end_date > start_date,
    )
    if exclude_id is not None:
        query = query.where(Budget.id != exclude_id)
    existing = db.execute(query).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Overlaps with existing period {existing.start_date} – {existing.end_date}",
        )


@router.get("", response_model=list[BudgetSummary])
def list_budgets(db: Session = Depends(get_db)):
    """List all budget periods (summary view)."""
    budgets = db.execute(
        select(Budget).order_by(Budget.start_date.desc())
    ).scalars().all()
    return [
        BudgetSummary(
            id=b.id,
            start_date=b.start_date,
            end_date=b.end_date,
            line_count=len(b.lines),
            created_at=b.created_at,
            updated_at=b.updated_at,
        )
        for b in budgets
    ]


@router.post("", response_model=BudgetOut, status_code=201)
def create_budget(data: BudgetCreate, db: Session = Depends(get_db)):
    """Create a new budget period. Rejects overlapping date ranges."""
    if data.start_date >= data.end_date:
        raise HTTPException(status_code=422, detail="start_date must be before end_date")

    _check_overlap(db, data.start_date, data.end_date)

    if data.lines:
        budget = Budget(start_date=data.start_date, end_date=data.end_date)
        db.add(budget)
        db.flush()
        for line_data in data.lines:
            cat = db.get(Category, line_data.category_id)
            if not cat:
                raise HTTPException(status_code=404, detail=f"Category {line_data.category_id} not found")
            db.add(BudgetLine(
                budget_id=budget.id,
                category_id=line_data.category_id,
                amount=line_data.amount,
            ))
        db.commit()
        db.refresh(budget)
    else:
        budget = _create_from_template(db, data.start_date, data.end_date)

    return _budget_to_out(budget, db)


@router.get("/{budget_id}", response_model=BudgetOut)
def get_budget(budget_id: int, db: Session = Depends(get_db)):
    """Get a budget by ID."""
    budget = db.get(Budget, budget_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    return _budget_to_out(budget, db)


@router.put("/{budget_id}", response_model=BudgetOut)
def update_budget(
    budget_id: int,
    data: BudgetUpdate,
    update_template: bool = False,
    db: Session = Depends(get_db),
):
    """Update a budget (replaces all lines). Budget must exist."""
    budget = db.get(Budget, budget_id)
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


@router.patch("/{budget_id}", response_model=BudgetOut)
def patch_budget(budget_id: int, data: BudgetPatch, db: Session = Depends(get_db)):
    """Update a budget's date range."""
    budget = db.get(Budget, budget_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    new_start = data.start_date if data.start_date is not None else budget.start_date
    new_end = data.end_date if data.end_date is not None else budget.end_date

    if new_start >= new_end:
        raise HTTPException(status_code=422, detail="start_date must be before end_date")

    _check_overlap(db, new_start, new_end, exclude_id=budget_id)

    budget.start_date = new_start
    budget.end_date = new_end
    db.commit()
    db.refresh(budget)
    return _budget_to_out(budget, db)


@router.delete("/{budget_id}")
def delete_budget(budget_id: int, db: Session = Depends(get_db)):
    """Delete a budget."""
    budget = db.get(Budget, budget_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    db.delete(budget)
    db.commit()
    return {"ok": True}
