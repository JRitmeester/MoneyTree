from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import Budget, BudgetLine, Category as CategoryModel, LineItem, Receipt, Transaction
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

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_auth)])


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

from dataclasses import dataclass
from typing import Optional as Opt


@dataclass
class ExpenseItem:
    tx: "Transaction"
    amount: float          # positive spend amount
    category_id: Opt[int]
    li: Opt["LineItem"]    # None for direct (receipt-less) transactions


def _iter_expense_items(db: Session, date_from: date | None, date_to: date | None):
    """Yield ExpenseItem for every expense, covering two paths:
    1. Transactions with receipts → one entry per line item.
    2. Transactions without any receipt → one entry for the full bedrag.
    """
    def _date_filter(q):
        if date_from:
            q = q.where(Transaction.datum >= date_from)
        if date_to:
            q = q.where(Transaction.datum <= date_to)
        return q

    # Path 1: line items
    li_query = _date_filter(
        select(Transaction, LineItem)
        .join(Receipt, Receipt.transaction_id == Transaction.id)
        .join(LineItem, LineItem.receipt_id == Receipt.id)
        .where(Transaction.bedrag < 0)
    )
    for tx, li in db.execute(li_query).all():
        yield ExpenseItem(tx=tx, amount=li.amount * li.quantity, category_id=li.category_id, li=li)

    # Path 2: transactions with no receipt at all
    no_receipt_query = _date_filter(
        select(Transaction)
        .where(Transaction.bedrag < 0)
        .where(
            ~select(Receipt.id)
            .where(Receipt.transaction_id == Transaction.id)
            .exists()
        )
    )
    for tx in db.execute(no_receipt_query).scalars().all():
        yield ExpenseItem(tx=tx, amount=abs(tx.bedrag), category_id=tx.category_id, li=None)


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

    groups: dict[int | str, dict] = {}
    counted_txs: dict[int | str, set] = {}
    cats_with_spending: set[int] = set()

    for item in _iter_expense_items(db, date_from, date_to):
        if item.category_id is None:
            key = "Uncategorized"
        else:
            cats_with_spending.add(item.category_id)
            key = _find_root(item.category_id, cat_id_to_cat)

        if key not in groups:
            groups[key] = {"total": 0.0}
            counted_txs[key] = set()
        groups[key]["total"] += item.amount
        counted_txs[key].add(item.tx.id)

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
    return [r for r in result if r.category_id is not None]


@router.get("/by-category-children/{category_id}", response_model=list[CategorySpending])
def get_by_category_children(
    category_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    """Spending grouped by direct children of a given category."""
    cat_id_to_cat, children_by_parent = _build_hierarchy(db)

    groups: dict[int, dict] = {}
    counted_txs: dict[int, set] = {}
    cats_with_spending: set[int] = set()

    for item in _iter_expense_items(db, date_from, date_to):
        if item.category_id is None:
            continue
        cats_with_spending.add(item.category_id)
        if not _is_descendant_of(item.category_id, category_id, cat_id_to_cat):
            continue
        child_id = _find_direct_child_ancestor(item.category_id, category_id, children_by_parent, cat_id_to_cat)
        if child_id is None:
            continue
        if child_id not in groups:
            groups[child_id] = {"total": 0.0}
            counted_txs[child_id] = set()
        groups[child_id]["total"] += item.amount
        counted_txs[child_id].add(item.tx.id)

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

    items = []
    total = 0.0
    for item in _iter_expense_items(db, date_from, date_to):
        if item.category_id is None:
            continue
        if not _is_descendant_of(item.category_id, category_id, cat_id_to_cat):
            continue
        total += item.amount
        if item.li is not None:
            items.append(SpendingLineItem(
                line_item_id=item.li.id,
                description=item.li.description,
                amount=item.li.amount,
                quantity=item.li.quantity,
                category_id=item.category_id,
                category_name=item.li.category.name if item.li.category else None,
                is_remaining=item.li.is_remaining,
                transaction_id=item.tx.id,
                transaction_date=item.tx.datum,
                transaction_merchant=item.tx.merchant_name or item.tx.naam,
                transaction_amount=item.tx.bedrag,
            ))
        else:
            # Direct transaction (no receipt)
            items.append(SpendingLineItem(
                line_item_id=None,
                description=item.tx.merchant_name or item.tx.naam or item.tx.omschrijving[:60],
                amount=item.amount,
                quantity=1,
                category_id=item.category_id,
                category_name=item.tx.category.name if item.tx.category else None,
                is_remaining=False,
                transaction_id=item.tx.id,
                transaction_date=item.tx.datum,
                transaction_merchant=item.tx.merchant_name or item.tx.naam,
                transaction_amount=item.tx.bedrag,
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

    all_cats = db.execute(select(CategoryModel)).scalars().all()
    categories = {c.id: c for c in all_cats}

    actuals: dict[int, float] = {}
    unmapped_expenses = 0.0
    unmapped_income = 0.0

    for item in _iter_expense_items(db, first_day, last_day):
        is_income = item.tx.bedrag > 0
        if item.category_id is None:
            if is_income:
                unmapped_income += item.amount
            else:
                unmapped_expenses += item.amount
            continue
        actuals[item.category_id] = actuals.get(item.category_id, 0.0) + item.amount

    # Also count income transactions (not covered by _iter_expense_items)
    income_query = (
        select(Transaction, LineItem)
        .join(Receipt, Receipt.transaction_id == Transaction.id)
        .join(LineItem, LineItem.receipt_id == Receipt.id)
        .where(Transaction.bedrag > 0)
        .where(Transaction.datum >= first_day, Transaction.datum <= last_day)
    )
    for tx, li in db.execute(income_query).all():
        if li.category_id is None:
            unmapped_income += li.amount * li.quantity
        else:
            actuals[li.category_id] = actuals.get(li.category_id, 0.0) + li.amount * li.quantity

    # Direct income transactions (no receipt)
    direct_income_query = (
        select(Transaction)
        .where(Transaction.bedrag > 0)
        .where(Transaction.datum >= first_day, Transaction.datum <= last_day)
        .where(~select(Receipt.id).where(Receipt.transaction_id == Transaction.id).exists())
    )
    for tx in db.execute(direct_income_query).scalars().all():
        if tx.category_id is None:
            unmapped_income += tx.bedrag
        else:
            actuals[tx.category_id] = actuals.get(tx.category_id, 0.0) + tx.bedrag

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

    from .budget import _savings_balances
    balances = _savings_balances(db)

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
            balance=balances.get(cat_id, 0.0),
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
