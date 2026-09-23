"""Budget-vs-actual computation, shared by the dashboard endpoint and (in a
later task) the highlights engine.

`_iter_expense_items`, `_offset_totals`, and the `ExpenseItem` dataclass used
to live in routers/dashboard.py; they moved here because `compute_budget_actuals`
needs them and several other dashboard endpoints also use them. dashboard.py
imports them back from this module so those call sites are unaffected.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional as Opt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Budget, Category as CategoryModel, LineItem, Receipt, Transaction, TransactionOffset
from .category_paths import full_category_path


@dataclass
class ExpenseItem:
    tx: "Transaction"
    amount: float          # positive spend amount
    category_id: Opt[int]
    li: Opt["LineItem"]    # None for direct (receipt-less) transactions


def _offset_totals(db: Session) -> tuple[dict[int, float], set[int]]:
    """One query, reused by every analytics endpoint: no N+1.

    Returns:
    - expense_id -> total linked-offset amount (sum of abs(bedrag) of every
      income transaction linked to that expense).
    - the set of income transaction ids that are linked as an offset to some
      expense (these are excluded from income everywhere).

    Offsets aren't themselves date-scoped: a link is a permanent property of
    the two transactions, so this is not filtered by date_from/date_to. Each
    endpoint applies the date filter to which transactions it looks at, not
    to which offsets exist.
    """
    rows = db.execute(
        select(
            TransactionOffset.expense_transaction_id,
            TransactionOffset.income_transaction_id,
            Transaction.bedrag,
        ).join(Transaction, Transaction.id == TransactionOffset.income_transaction_id)
    ).all()

    expense_offsets: dict[int, float] = {}
    offset_income_ids: set[int] = set()
    for expense_id, income_id, income_bedrag in rows:
        expense_offsets[expense_id] = expense_offsets.get(expense_id, 0.0) + abs(income_bedrag)
        offset_income_ids.add(income_id)
    return expense_offsets, offset_income_ids


def _iter_expense_items(
    db: Session,
    date_from: date | None,
    date_to: date | None,
    expense_offsets: dict[int, float] | None = None,
):
    """Yield ExpenseItem for every expense, covering two paths:
    1. Transactions with receipts → one entry per line item.
    2. Transactions without any receipt → one entry for the full bedrag.

    `expense_offsets` lets a caller that already fetched `_offset_totals`
    (e.g. because it also needs `offset_income_ids`) pass the dict through
    instead of triggering a second identical query. When omitted, it is
    computed here.

    Offset double-subtract invariant: when an income transaction is linked as
    an offset to a receipted expense, `link_offset` immediately calls
    `recalculate_remaining` (services/remaining.py), which subtracts the
    offset total from the receipt's "remaining" line item on the spot. So by
    the time we get here, path 1's line items (explicit items + remaining)
    already sum to `abs(bedrag) - offset_total`. Subtracting the offset again
    here would double-count it. Path 2 (no receipt at all) has no line items
    to carry that adjustment, so it is the only path that subtracts the
    offset directly, floored at 0 so an offset can't flip an expense to
    "negative spend". This is also why transaction-level aggregations
    elsewhere in this module (summary, monthly-trend, savings-capacity, which
    never see line items) always subtract the offset from raw `bedrag`: they
    have no equivalent of the already-adjusted remaining line item to lean on.
    """
    if expense_offsets is None:
        expense_offsets, _ = _offset_totals(db)

    def _date_filter(q):
        if date_from:
            q = q.where(Transaction.datum >= date_from)
        if date_to:
            q = q.where(Transaction.datum <= date_to)
        return q

    # Path 1: line items, already net of any linked offset, do NOT subtract again.
    li_query = _date_filter(
        select(Transaction, LineItem)
        .join(Receipt, Receipt.transaction_id == Transaction.id)
        .join(LineItem, LineItem.receipt_id == Receipt.id)
        .where(Transaction.bedrag < 0)
        .where(Transaction.is_internal_transfer.is_(False))
    )
    for tx, li in db.execute(li_query).all():
        yield ExpenseItem(tx=tx, amount=li.amount * li.quantity, category_id=li.category_id, li=li)

    # Path 2: transactions with no receipt at all: subtract the offset here,
    # floored at 0.
    no_receipt_query = _date_filter(
        select(Transaction)
        .where(Transaction.bedrag < 0)
        .where(Transaction.is_internal_transfer.is_(False))
        .where(
            ~select(Receipt.id)
            .where(Receipt.transaction_id == Transaction.id)
            .exists()
        )
    )
    for tx in db.execute(no_receipt_query).scalars().all():
        # Floored at 0: if the offset exceeds the expense, the surplus is
        # dropped from net rather than counted as extra income. The income
        # side is already fully excluded from income totals elsewhere, so
        # this surplus simply disappears from analytics rather than being
        # double-counted.
        amount = max(0.0, abs(tx.bedrag) - expense_offsets.get(tx.id, 0.0))
        yield ExpenseItem(tx=tx, amount=amount, category_id=tx.category_id, li=None)


# ---------------------------------------------------------------------------
# Budget-vs-actual
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetActualLine:
    category_id: int
    category_name: str
    category_type: str
    is_fixed: bool
    budgeted: float
    actual: float
    difference: float
    percentage: float
    balance: float
    source: str


@dataclass(frozen=True)
class BudgetActualsResult:
    budget_id: int
    start_date: date
    end_date: date
    total_budgeted_income: float
    total_actual_income: float
    total_budgeted_expenses: float
    total_actual_expenses: float
    budgeted_net: float
    actual_net: float
    savings_rate: float
    income_lines: tuple[BudgetActualLine, ...]
    expense_lines: tuple[BudgetActualLine, ...]
    unmapped_expenses: float
    unmapped_income: float


def compute_budget_actuals(db: Session, budget: Budget) -> BudgetActualsResult:
    """Compare budgeted amounts with actual transactions for a budget period.

    Moved verbatim from the `/budget-vs-actual/{budget_id}` endpoint so the
    highlights engine can consume the same actuals the dashboard shows,
    instead of re-deriving them.
    """
    # Budget periods are half-open [start_date, end_date): a transaction on
    # end_date belongs to the NEXT period. The queries below filter with an
    # inclusive `datum <= last_day`, so step the boundary back one day.
    first_day = budget.start_date
    last_day = budget.end_date - timedelta(days=1)

    all_cats = db.execute(select(CategoryModel)).scalars().all()
    categories = {c.id: c for c in all_cats}

    actuals: dict[int, float] = {}
    unmapped_expenses = 0.0
    unmapped_income = 0.0

    expense_offsets, offset_income_ids = _offset_totals(db)

    for item in _iter_expense_items(db, first_day, last_day, expense_offsets):
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
        .where(Transaction.is_internal_transfer.is_(False))
    )
    for tx, li in db.execute(income_query).all():
        if tx.id in offset_income_ids:
            continue
        if li.category_id is None:
            unmapped_income += li.amount * li.quantity
        else:
            actuals[li.category_id] = actuals.get(li.category_id, 0.0) + li.amount * li.quantity

    # Direct income transactions (no receipt)
    direct_income_query = (
        select(Transaction)
        .where(Transaction.bedrag > 0)
        .where(Transaction.datum >= first_day, Transaction.datum <= last_day)
        .where(Transaction.is_internal_transfer.is_(False))
        .where(~select(Receipt.id).where(Receipt.transaction_id == Transaction.id).exists())
    )
    for tx in db.execute(direct_income_query).scalars().all():
        if tx.id in offset_income_ids:
            continue
        if tx.category_id is None:
            unmapped_income += tx.bedrag
        else:
            actuals[tx.category_id] = actuals.get(tx.category_id, 0.0) + tx.bedrag

    budgeted_by_cat: dict[int, float] = {}
    source_by_cat: dict[int, str] = {}
    for line in budget.lines:
        budgeted_by_cat[line.category_id] = line.amount
        source_by_cat[line.category_id] = line.source

    # Savings goals: "actual" answers "did I put money toward this goal this
    # period". Spending analytics exclude internal transfers, so a savings
    # line's spending-actual is (correctly) ~0 and tells the user nothing.
    # Instead, use the net of internal transfers categorized to the pot:
    # deposits from checking count positive, withdrawals negative.
    savings_cat_ids = {c.id for c in all_cats if c.category_type == "savings"}
    if savings_cat_ids:
        contribution_rows = db.execute(
            select(Transaction.category_id, func.sum(Transaction.bedrag))
            .where(
                Transaction.is_internal_transfer.is_(True),
                Transaction.category_id.in_(savings_cat_ids),
                Transaction.datum >= first_day,
                Transaction.datum <= last_day,
            )
            .group_by(Transaction.category_id)
        ).all()
        for cat_id, net_bedrag in contribution_rows:
            # Outgoing transfers (to savings) have negative bedrag on the
            # imported checking account, so contributions = -net.
            actuals[cat_id] = round(-net_bedrag, 2)

    all_cat_ids = set(budgeted_by_cat.keys()) | set(actuals.keys())

    income_lines: list[BudgetActualLine] = []
    expense_lines: list[BudgetActualLine] = []
    total_budgeted_income = 0.0
    total_actual_income = 0.0
    total_budgeted_expenses = 0.0
    total_actual_expenses = 0.0

    # Deferred import: routers/budget.py has no module-level dependency on
    # this service, so this stays a plain function-local import mirroring the
    # pattern the endpoint used before the move (kept to avoid re-introducing
    # any import-order sensitivity between routers and services).
    from ..routers.budget import _savings_balances
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

        line = BudgetActualLine(
            category_id=cat_id,
            category_name=full_category_path(cat_id, categories),
            category_type=cat.category_type,
            is_fixed=cat.is_fixed,
            budgeted=budgeted,
            actual=actual,
            difference=difference,
            percentage=percentage,
            balance=balances.get(cat_id, 0.0),
            source=source_by_cat.get(cat_id, "manual"),
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

    return BudgetActualsResult(
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
        income_lines=tuple(income_lines),
        expense_lines=tuple(expense_lines),
        unmapped_expenses=unmapped_expenses,
        unmapped_income=unmapped_income,
    )
