from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Budget, Category as CategoryModel, LineItem, Receipt, Transaction
from ..schemas import (
    BreadcrumbItem,
    BudgetVsActualLine,
    BudgetVsActualSummary,
    CategoryDetail,
    CategorySpending,
    DashboardSummary,
    MonthlyTrend,
    SpendingLineItem,
    SubcategorySpending,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ---------------------------------------------------------------------------
# Hierarchy helpers (replaces category_resolver — ID-based only, no strings)
# ---------------------------------------------------------------------------

def _build_hierarchy(db: Session) -> tuple[dict, dict]:
    """Return (cat_id_to_cat, children_by_parent) dicts."""
    cats = db.execute(select(CategoryModel)).scalars().all()
    cat_id_to_cat = {c.id: c for c in cats}
    children_by_parent: dict[int | None, list[int]] = {}
    for c in cats:
        children_by_parent.setdefault(c.parent_id, []).append(c.id)
    return cat_id_to_cat, children_by_parent


def _find_root(cat_id: int, cat_id_to_cat: dict) -> int:
    seen = set()
    current = cat_id
    while current in cat_id_to_cat:
        cat = cat_id_to_cat[current]
        if cat.parent_id is None or cat.parent_id in seen:
            return current
        seen.add(current)
        current = cat.parent_id
    return current


def _is_descendant_of(cat_id: int, ancestor_id: int, cat_id_to_cat: dict) -> bool:
    if cat_id == ancestor_id:
        return True
    seen = set()
    current = cat_id
    while current in cat_id_to_cat:
        if current == ancestor_id:
            return True
        cat = cat_id_to_cat[current]
        if cat.parent_id is None or cat.parent_id in seen:
            return False
        seen.add(current)
        current = cat.parent_id
    return False


def _find_direct_child_ancestor(cat_id: int, parent_id: int, children_by_parent: dict, cat_id_to_cat: dict) -> int | None:
    if cat_id == parent_id:
        return None
    direct_children = set(children_by_parent.get(parent_id, []))
    seen = set()
    current = cat_id
    while current in cat_id_to_cat:
        if current in direct_children:
            return current
        cat = cat_id_to_cat[current]
        if cat.parent_id is None or cat.parent_id in seen:
            return None
        seen.add(current)
        current = cat.parent_id
    return None


def _get_direct_children(cat_id: int, children_by_parent: dict) -> list[int]:
    return children_by_parent.get(cat_id, [])


# ---------------------------------------------------------------------------
# Shared query helper
# ---------------------------------------------------------------------------

def _get_expense_line_items(db: Session, date_from: date | None, date_to: date | None):
    """Fetch all expense line items with their transactions."""
    query = (
        select(Transaction, LineItem)
        .join(Receipt, Receipt.transaction_id == Transaction.id)
        .join(LineItem, LineItem.receipt_id == Receipt.id)
        .where(Transaction.bedrag < 0)
    )
    if date_from:
        query = query.where(Transaction.datum >= date_from)
    if date_to:
        query = query.where(Transaction.datum <= date_to)
    return db.execute(query).all()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=DashboardSummary)
def get_summary(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    """Overall income/expenses/net for a period."""
    query = select(Transaction)
    if date_from:
        query = query.where(Transaction.datum >= date_from)
    if date_to:
        query = query.where(Transaction.datum <= date_to)

    transactions = db.execute(query).scalars().all()

    total_income = sum(tx.bedrag for tx in transactions if tx.bedrag > 0)
    total_expenses = sum(tx.bedrag for tx in transactions if tx.bedrag < 0)
    net = total_income + total_expenses

    tx_ids = [tx.id for tx in transactions]
    receipts_attached = 0
    if tx_ids:
        receipts_attached = db.execute(
            select(func.count()).select_from(Receipt).where(
                Receipt.transaction_id.in_(tx_ids)
            )
        ).scalar() or 0

    return DashboardSummary(
        total_income=total_income,
        total_expenses=abs(total_expenses),
        net=net,
        transaction_count=len(transactions),
        receipts_attached=receipts_attached,
    )


@router.get("/by-category", response_model=list[CategorySpending])
def get_by_category(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    """Spending breakdown grouped by root category (expenses only)."""
    cat_id_to_cat, children_by_parent = _build_hierarchy(db)
    rows = _get_expense_line_items(db, date_from, date_to)

    groups: dict[int | str, dict] = {}
    counted_txs: dict[int | str, set] = {}
    cats_with_spending: set[int] = set()

    for tx, li in rows:
        if li.category_id is None:
            key = "Uncategorized"
        else:
            cats_with_spending.add(li.category_id)
            key = _find_root(li.category_id, cat_id_to_cat)

        if key not in groups:
            groups[key] = {"total": 0.0}
            counted_txs[key] = set()
        groups[key]["total"] += li.amount * li.quantity
        counted_txs[key].add(tx.id)

    def has_spending_children(cat_id: int) -> bool:
        for child_id in _get_direct_children(cat_id, children_by_parent):
            if child_id in cats_with_spending:
                return True
            if has_spending_children(child_id):
                return True
        return False

    result = []
    for key, data in groups.items():
        if isinstance(key, int):
            cat = cat_id_to_cat.get(key)
            name = cat.name if cat else f"Category #{key}"
            children = has_spending_children(key)
        else:
            name = key
            children = False

        result.append(CategorySpending(
            category=name,
            category_id=key if isinstance(key, int) else None,
            total=data["total"],
            count=len(counted_txs[key]),
            has_children=children,
        ))

    result.sort(key=lambda x: x.total, reverse=True)
    return result


@router.get("/by-category-children/{category_id}", response_model=list[CategorySpending])
def get_by_category_children(
    category_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    """Spending grouped by direct children of a given category."""
    cat_id_to_cat, children_by_parent = _build_hierarchy(db)
    rows = _get_expense_line_items(db, date_from, date_to)

    groups: dict[int, dict] = {}
    counted_txs: dict[int, set] = {}
    cats_with_spending: set[int] = set()

    for tx, li in rows:
        if li.category_id is None:
            continue
        cats_with_spending.add(li.category_id)
        if not _is_descendant_of(li.category_id, category_id, cat_id_to_cat):
            continue
        child_id = _find_direct_child_ancestor(li.category_id, category_id, children_by_parent, cat_id_to_cat)
        if child_id is None:
            continue
        if child_id not in groups:
            groups[child_id] = {"total": 0.0}
            counted_txs[child_id] = set()
        groups[child_id]["total"] += li.amount * li.quantity
        counted_txs[child_id].add(tx.id)

    def has_spending_descendants(cat_id: int) -> bool:
        for cid in _get_direct_children(cat_id, children_by_parent):
            if cid in cats_with_spending:
                return True
            if has_spending_descendants(cid):
                return True
        return False

    result = []
    for child_id, data in groups.items():
        cat = cat_id_to_cat.get(child_id)
        name = cat.name if cat else f"Category #{child_id}"
        result.append(CategorySpending(
            category=name,
            category_id=child_id,
            total=data["total"],
            count=len(counted_txs[child_id]),
            has_children=has_spending_descendants(child_id),
        ))

    result.sort(key=lambda x: x.total, reverse=True)
    return result


@router.get("/category/{category_id}/line-items", response_model=CategoryDetail)
def get_category_line_items(
    category_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    """Line items under a category (including descendants), with transaction context."""
    cat_id_to_cat, _ = _build_hierarchy(db)
    cat = cat_id_to_cat.get(category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    # Build breadcrumb
    breadcrumb = []
    current = category_id
    while current in cat_id_to_cat:
        c = cat_id_to_cat[current]
        breadcrumb.append(BreadcrumbItem(id=c.id, name=c.name))
        if c.parent_id is None:
            break
        current = c.parent_id
    breadcrumb.reverse()

    rows = _get_expense_line_items(db, date_from, date_to)

    items = []
    total = 0.0
    for tx, li in rows:
        if li.category_id is None:
            continue
        if not _is_descendant_of(li.category_id, category_id, cat_id_to_cat):
            continue
        li_total = li.amount * li.quantity
        total += li_total
        items.append(SpendingLineItem(
            line_item_id=li.id,
            description=li.description,
            amount=li.amount,
            quantity=li.quantity,
            category_id=li.category_id,
            category_name=li.category.name if li.category else None,
            is_remaining=li.is_remaining,
            transaction_id=tx.id,
            transaction_date=tx.datum,
            transaction_merchant=tx.merchant_name or tx.naam,
            transaction_amount=tx.bedrag,
        ))

    items.sort(key=lambda x: x.transaction_date, reverse=True)

    return CategoryDetail(
        category_id=category_id,
        category_name=cat.name,
        breadcrumb=breadcrumb,
        total=round(total, 2),
        line_items=items,
    )


@router.get("/monthly-trend", response_model=list[MonthlyTrend])
def get_monthly_trend(
    months: int = Query(6, ge=1, le=24),
    db: Session = Depends(get_db),
):
    """Monthly income/expenses over time."""
    transactions = db.execute(
        select(Transaction).order_by(Transaction.datum)
    ).scalars().all()

    monthly: dict[str, dict] = {}
    for tx in transactions:
        key = tx.datum.strftime("%Y-%m")
        if key not in monthly:
            monthly[key] = {"income": 0.0, "expenses": 0.0}
        if tx.bedrag > 0:
            monthly[key]["income"] += tx.bedrag
        else:
            monthly[key]["expenses"] += abs(tx.bedrag)

    sorted_months = sorted(monthly.keys())[-months:]

    return [
        MonthlyTrend(
            month=m,
            income=monthly[m]["income"],
            expenses=monthly[m]["expenses"],
            net=monthly[m]["income"] - monthly[m]["expenses"],
        )
        for m in sorted_months
    ]


@router.get("/budget-vs-actual/{budget_id}", response_model=BudgetVsActualSummary)
def get_budget_vs_actual(budget_id: int, db: Session = Depends(get_db)):
    """Compare budgeted amounts with actual transactions for a budget period."""
    budget = db.get(Budget, budget_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")

    first_day = budget.start_date
    last_day = budget.end_date

    query = (
        select(Transaction, LineItem)
        .join(Receipt, Receipt.transaction_id == Transaction.id)
        .join(LineItem, LineItem.receipt_id == Receipt.id)
        .where(
            Transaction.datum >= first_day,
            Transaction.datum <= last_day,
        )
    )
    rows = db.execute(query).all()

    all_cats = db.execute(select(CategoryModel)).scalars().all()
    categories = {c.id: c for c in all_cats}

    actuals: dict[int, float] = {}
    unmapped_expenses = 0.0
    unmapped_income = 0.0

    for tx, li in rows:
        li_amount = li.amount * li.quantity
        is_income = tx.bedrag > 0

        if li.category_id is None:
            if is_income:
                unmapped_income += li_amount
            else:
                unmapped_expenses += li_amount
            continue

        actuals[li.category_id] = actuals.get(li.category_id, 0.0) + li_amount

    budgeted_by_cat: dict[int, float] = {}
    for line in budget.lines:
        budgeted_by_cat[line.category_id] = line.amount

    all_cat_ids = set(budgeted_by_cat.keys()) | set(actuals.keys())

    income_lines = []
    expense_lines = []
    total_budgeted_income = 0.0
    total_actual_income = 0.0
    total_budgeted_expenses = 0.0
    total_actual_expenses = 0.0

    for cat_id in sorted(all_cat_ids):
        cat = categories.get(cat_id)
        if not cat:
            continue

        budgeted = budgeted_by_cat.get(cat_id, 0.0)
        actual = actuals.get(cat_id, 0.0)

        if cat.category_type == "income":
            difference = actual - budgeted
            total_budgeted_income += budgeted
            total_actual_income += actual
        else:
            difference = budgeted - actual
            total_budgeted_expenses += budgeted
            total_actual_expenses += actual

        percentage = (actual / budgeted * 100) if budgeted > 0 else 0.0

        line = BudgetVsActualLine(
            category_id=cat_id,
            category_name=cat.name,
            category_type=cat.category_type,
            is_fixed=cat.is_fixed,
            budgeted=budgeted,
            actual=actual,
            difference=difference,
            percentage=percentage,
        )

        if cat.category_type == "income":
            income_lines.append(line)
        else:
            expense_lines.append(line)

    income_lines.sort(key=lambda x: x.actual, reverse=True)
    expense_lines.sort(key=lambda x: x.actual, reverse=True)

    budgeted_net = total_budgeted_income - total_budgeted_expenses
    actual_net = total_actual_income - total_actual_expenses
    savings_rate = (actual_net / total_actual_income * 100) if total_actual_income > 0 else 0.0

    return BudgetVsActualSummary(
        budget_id=budget.id,
        start_date=budget.start_date,
        end_date=budget.end_date,
        total_budgeted_income=total_budgeted_income,
        total_actual_income=total_actual_income,
        total_budgeted_expenses=total_budgeted_expenses,
        total_actual_expenses=total_actual_expenses,
        budgeted_net=budgeted_net,
        actual_net=actual_net,
        savings_rate=savings_rate,
        income_lines=income_lines,
        expense_lines=expense_lines,
        unmapped_expenses=unmapped_expenses,
        unmapped_income=unmapped_income,
    )
