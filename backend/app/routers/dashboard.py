from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, extract, case
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Budget, Category as CategoryModel, CategoryMapping, LineItem, Receipt, Transaction
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
from ..services.category_resolver import (
    build_resolver,
    find_root,
    resolve_category,
    has_children as cat_has_children,
    is_descendant_of,
    find_direct_child_ancestor,
    get_direct_children,
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


def _get_expense_line_items(db: Session, date_from: date | None, date_to: date | None):
    """Shared helper: fetch all expense line items with their transactions."""
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


@router.get("/by-category", response_model=list[CategorySpending])
def get_by_category(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    """Spending breakdown grouped by root category (expenses only)."""
    resolver = build_resolver(db)
    rows = _get_expense_line_items(db, date_from, date_to)

    # Group by root category
    # Key: root_cat_id (int) or raw string for unresolved
    groups: dict[int | str, dict] = {}
    counted_txs: dict[int | str, set] = {}
    # Track which resolved category IDs have spending (for has_children check)
    cats_with_spending: set[int] = set()

    for tx, li in rows:
        cat_str = li.category or "Uncategorized"
        resolved_id, root_id = resolve_category(cat_str, resolver)

        if root_id is not None:
            key = root_id
        else:
            key = cat_str  # unresolved — use raw string

        if resolved_id is not None:
            cats_with_spending.add(resolved_id)

        if key not in groups:
            groups[key] = {"total": 0.0}
            counted_txs[key] = set()
        groups[key]["total"] += li.amount * li.quantity
        counted_txs[key].add(tx.id)

    def has_spending_children(cat_id: int) -> bool:
        """Check if any direct child of cat_id has spending (or descendants with spending)."""
        for child_id in get_direct_children(cat_id, resolver):
            if child_id in cats_with_spending:
                return True
            # Check if any descendant of child has spending
            if has_spending_children(child_id):
                return True
        return False

    result = []
    for key, data in groups.items():
        if isinstance(key, int):
            cat = resolver.cat_id_to_cat.get(key)
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
    resolver = build_resolver(db)
    rows = _get_expense_line_items(db, date_from, date_to)

    # Group by direct child of category_id
    groups: dict[int, dict] = {}
    counted_txs: dict[int, set] = {}
    cats_with_spending: set[int] = set()

    for tx, li in rows:
        cat_str = li.category or ""
        resolved_id, _ = resolve_category(cat_str, resolver)
        if resolved_id is None:
            continue

        cats_with_spending.add(resolved_id)

        # Check if this item is a descendant of category_id
        if not is_descendant_of(resolved_id, category_id, resolver):
            continue

        # Find which direct child of category_id this falls under
        child_id = find_direct_child_ancestor(resolved_id, category_id, resolver)
        if child_id is None:
            # Item is directly at this category level, not in any child
            continue

        if child_id not in groups:
            groups[child_id] = {"total": 0.0}
            counted_txs[child_id] = set()
        groups[child_id]["total"] += li.amount * li.quantity
        counted_txs[child_id].add(tx.id)

    def has_spending_descendants(cat_id: int) -> bool:
        for cid in get_direct_children(cat_id, resolver):
            if cid in cats_with_spending:
                return True
            if has_spending_descendants(cid):
                return True
        return False

    result = []
    for child_id, data in groups.items():
        cat = resolver.cat_id_to_cat.get(child_id)
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


@router.get("/by-subcategory", response_model=list[SubcategorySpending])
def get_by_subcategory(
    categorie: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    """Legacy detail view: non-remaining line items for a given category."""
    query = (
        select(Transaction, LineItem)
        .join(Receipt, Receipt.transaction_id == Transaction.id)
        .join(LineItem, LineItem.receipt_id == Receipt.id)
        .where(Transaction.bedrag < 0)
        .where(LineItem.is_remaining == False)  # noqa: E712
    )

    if categorie:
        matching_tx_ids = (
            select(Transaction.id)
            .join(Receipt, Receipt.transaction_id == Transaction.id)
            .join(LineItem, LineItem.receipt_id == Receipt.id)
            .where(LineItem.category == categorie)
        )
        query = query.where(Transaction.id.in_(matching_tx_ids))

    if date_from:
        query = query.where(Transaction.datum >= date_from)
    if date_to:
        query = query.where(Transaction.datum <= date_to)

    rows = db.execute(query).all()

    cats: dict[str, dict] = {}
    for tx, li in rows:
        cat = li.category or "Uncategorized"
        if cat not in cats:
            cats[cat] = {"total": 0.0, "count": 0}
        cats[cat]["total"] += li.amount * li.quantity
        cats[cat]["count"] += 1

    result = [
        SubcategorySpending(category=cat, total=data["total"], count=data["count"])
        for cat, data in cats.items()
    ]
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
    from fastapi import HTTPException

    resolver = build_resolver(db)
    cat = resolver.cat_id_to_cat.get(category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    # Build breadcrumb: walk from this category up to root
    breadcrumb = []
    current = category_id
    while current in resolver.cat_id_to_cat:
        c = resolver.cat_id_to_cat[current]
        breadcrumb.append(BreadcrumbItem(id=c.id, name=c.name))
        if c.parent_id is None:
            break
        current = c.parent_id
    breadcrumb.reverse()

    rows = _get_expense_line_items(db, date_from, date_to)

    items = []
    total = 0.0
    for tx, li in rows:
        cat_str = li.category or ""
        resolved_id, _ = resolve_category(cat_str, resolver)
        if resolved_id is None:
            continue
        if not is_descendant_of(resolved_id, category_id, resolver):
            continue

        li_total = li.amount * li.quantity
        total += li_total
        items.append(SpendingLineItem(
            line_item_id=li.id,
            description=li.description,
            amount=li.amount,
            quantity=li.quantity,
            category=li.category,
            is_remaining=li.is_remaining,
            transaction_id=tx.id,
            transaction_date=tx.datum,
            transaction_merchant=tx.merchant_name or tx.naam,
            transaction_amount=tx.bedrag,
        ))

    # Sort by transaction date descending
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

    # Load line items joined with transactions for the month
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

    # Build category name -> id lookup
    all_cats = db.execute(select(CategoryModel)).scalars().all()
    cat_name_to_id = {c.name: c.id for c in all_cats}
    categories = {c.id: c for c in all_cats}

    # CategoryMapping as fallback for bank category names
    mappings = db.execute(select(CategoryMapping)).scalars().all()
    mapping_dict = {m.bank_category: m.category_id for m in mappings}

    actuals: dict[int, float] = {}
    unmapped_expenses = 0.0
    unmapped_income = 0.0

    for tx, li in rows:
        cat_str = li.category or ""
        # Resolve to category_id: direct name match first, then mapping fallback
        cat_id = cat_name_to_id.get(cat_str) or mapping_dict.get(cat_str)

        li_amount = li.amount * li.quantity
        is_income = tx.bedrag > 0

        if cat_id is None:
            if is_income:
                unmapped_income += li_amount
            else:
                unmapped_expenses += li_amount
            continue

        actuals[cat_id] = actuals.get(cat_id, 0.0) + li_amount

    # Load budget
    budget = db.execute(
        select(Budget).where(Budget.year == year, Budget.month == month)
    ).scalar_one_or_none()

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
