from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, extract, case
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Budget, Category as CategoryModel, CategoryMapping, LineItem, Receipt, Transaction
from ..schemas import (
    BudgetVsActualLine,
    BudgetVsActualSummary,
    CategorySpending,
    DashboardSummary,
    MonthlyTrend,
    SubcategorySpending,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


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

    # Count receipts attached in this period
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
    """Spending breakdown by bank category (expenses only)."""
    query = select(Transaction).where(Transaction.bedrag < 0)
    if date_from:
        query = query.where(Transaction.datum >= date_from)
    if date_to:
        query = query.where(Transaction.datum <= date_to)

    transactions = db.execute(query).scalars().all()

    cats: dict[str, dict] = {}
    for tx in transactions:
        cat = tx.categorie or "Overig"
        if cat not in cats:
            cats[cat] = {"total": 0.0, "count": 0}
        cats[cat]["total"] += abs(tx.bedrag)
        cats[cat]["count"] += 1

    result = [
        CategorySpending(category=cat, total=data["total"], count=data["count"])
        for cat, data in cats.items()
    ]
    result.sort(key=lambda x: x.total, reverse=True)
    return result


@router.get("/by-subcategory", response_model=list[SubcategorySpending])
def get_by_subcategory(
    categorie: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    """Spending by line-item category — the drill-down view."""
    # Find transactions in scope
    tx_query = select(Transaction).where(Transaction.bedrag < 0)
    if categorie:
        tx_query = tx_query.where(Transaction.categorie == categorie)
    if date_from:
        tx_query = tx_query.where(Transaction.datum >= date_from)
    if date_to:
        tx_query = tx_query.where(Transaction.datum <= date_to)

    tx_ids = [tx.id for tx in db.execute(tx_query).scalars().all()]
    if not tx_ids:
        return []

    # Find receipts linked to those transactions
    receipt_ids = db.execute(
        select(Receipt.id).where(Receipt.transaction_id.in_(tx_ids))
    ).scalars().all()
    if not receipt_ids:
        return []

    # Aggregate line items by category
    items = db.execute(
        select(LineItem).where(LineItem.receipt_id.in_(receipt_ids))
    ).scalars().all()

    cats: dict[str, dict] = {}
    for item in items:
        raw = item.category or "Uncategorized"
        # Split comma-separated categories so each tag is counted individually
        tag_list = [t.strip() for t in raw.split(",") if t.strip()]
        if not tag_list:
            tag_list = ["Uncategorized"]
        item_total = item.amount * item.quantity
        for cat in tag_list:
            if cat not in cats:
                cats[cat] = {"total": 0.0, "count": 0}
            cats[cat]["total"] += item_total
            cats[cat]["count"] += 1

    result = [
        SubcategorySpending(category=cat, total=data["total"], count=data["count"])
        for cat, data in cats.items()
    ]
    result.sort(key=lambda x: x.total, reverse=True)
    return result


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

    # Sort by month and take last N
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


@router.get("/budget-vs-actual/{year}/{month}", response_model=BudgetVsActualSummary)
def get_budget_vs_actual(year: int, month: int, db: Session = Depends(get_db)):
    """Compare budgeted amounts with actual transactions for a given month."""
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])

    # Load transactions for the month
    transactions = db.execute(
        select(Transaction).where(
            Transaction.datum >= first_day,
            Transaction.datum <= last_day,
        )
    ).scalars().all()

    # Load all category mappings: bank_category -> category_id
    mappings = db.execute(select(CategoryMapping)).scalars().all()
    mapping_dict = {m.bank_category: m.category_id for m in mappings}

    # Load all categories for name/type lookup
    all_cats = db.execute(select(CategoryModel)).scalars().all()
    categories = {c.id: c for c in all_cats}

    # Aggregate actuals by category_id
    actuals: dict[int, float] = {}
    unmapped_expenses = 0.0
    unmapped_income = 0.0

    for tx in transactions:
        cat_id = mapping_dict.get(tx.categorie)
        if cat_id is None:
            if tx.bedrag > 0:
                unmapped_income += tx.bedrag
            else:
                unmapped_expenses += abs(tx.bedrag)
            continue
        actuals[cat_id] = actuals.get(cat_id, 0.0) + abs(tx.bedrag)

    # Load budget (optional — we can show actuals even without a budget)
    budget = db.execute(
        select(Budget).where(Budget.year == year, Budget.month == month)
    ).scalar_one_or_none()

    # Build lines from budget (if exists) merged with actuals
    budgeted_by_cat: dict[int, float] = {}
    if budget:
        for line in budget.lines:
            budgeted_by_cat[line.category_id] = line.amount

    # Collect all category IDs that appear in either budget or actuals
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
            budgeted=budgeted,
            actual=actual,
            difference=difference,
            percentage=percentage,
        )

        if cat.category_type == "income":
            income_lines.append(line)
        else:
            expense_lines.append(line)

    # Sort by actual amount descending
    income_lines.sort(key=lambda x: x.actual, reverse=True)
    expense_lines.sort(key=lambda x: x.actual, reverse=True)

    budgeted_net = total_budgeted_income - total_budgeted_expenses
    actual_net = total_actual_income - total_actual_expenses
    savings_rate = (actual_net / total_actual_income * 100) if total_actual_income > 0 else 0.0

    return BudgetVsActualSummary(
        year=year,
        month=month,
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
