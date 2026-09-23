"""Deterministic budget highlights engine.

Spec: .superpowers/sdd/2026-09-23-budget-highlights/spec.md (binding),
"Rule catalog" section, R1-R9 (R10 deferred to v1.1).

Consumes `compute_budget_actuals` (does not re-derive actuals) and the
period's raw transactions (for incidental normalization, the one-off
detector, top expenses, and pot withdrawal listings). Every rule is a pure
function of (actuals, transactions, budget lines, today); a rule that
errors on one line logs and skips it rather than raising, so one bad line
never takes down the whole panel.
"""
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional as Opt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Budget, Category as CategoryModel, IncidentalLabel, Transaction
from .budget_actuals import BudgetActualLine, _iter_expense_items, compute_budget_actuals
from .category_paths import full_category_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (module-level, tested; exact names/values from the spec)
# ---------------------------------------------------------------------------

OVERRUN_PCT = 0.20
OVERRUN_MIN_EUR = 25.0
UNDERRUN_FRACTION = 0.5
ONE_OFF_FRACTION = 0.5
BILL_INCREASE_FACTOR = 1.10
SALARY_CHANGE_PCT = 0.02
TOP_EXPENSES_COUNT = 3
CLIMATE_PERIODS = 3

SEVERITY_GOOD = "good"
SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"

# Rule catalog order: primary sort key for the final highlights list.
RULE_ORDER = {
    "fixed_ghost": 0,
    "bill_change": 1,
    "flexible_overrun": 2,
    "flexible_underrun": 3,
    "savings_funded": 4,
    "savings_no_transfer": 4,
    "savings_withdrawal": 4,
    "savings_partial": 4,
    "income_change": 5,
    "top_expenses": 6,
    "scorecard": 7,
}


def _r(x: float) -> float:
    """Round to cents. Every amount surfaced to the API goes through this."""
    return round(x, 2)


@dataclass(frozen=True)
class Highlight:
    rule: str
    severity: str
    title: str
    detail: str
    category_id: Opt[int]
    amount: Opt[float]


@dataclass(frozen=True)
class IncidentalLabelAmount:
    label: str
    amount: float


@dataclass(frozen=True)
class HighlightsSummary:
    raw_net: float
    incidental_total: float
    incidental_by_label: tuple[IncidentalLabelAmount, ...]
    unlabeled_incidental: float
    structural_net: float
    flexible_within_plan: int
    flexible_total: int
    pots_executed: int
    pots_planned: int


@dataclass(frozen=True)
class HighlightsResult:
    budget_id: int
    start_date: date
    end_date: date
    closed: bool
    summary: HighlightsSummary
    highlights: tuple[Highlight, ...]


# ---------------------------------------------------------------------------
# Category tree helpers (subtree aggregation, R4/R5/R9)
# ---------------------------------------------------------------------------


def _children_map(all_cats: list[CategoryModel]) -> dict[int, list[int]]:
    children: dict[int, list[int]] = {}
    for cat in all_cats:
        if cat.parent_id is not None:
            children.setdefault(cat.parent_id, []).append(cat.id)
    return children


def _foldable_descendants(
    cat_id: int, children: dict[int, list[int]], line_category_ids: set[int]
) -> set[int]:
    """Descendants of cat_id whose actuals fold into cat_id's aggregate: every
    descendant that does not itself carry an explicit plan line in this
    budget. A descendant WITH its own line stops the fold (nearest-ancestor
    semantics): it is excluded, and its own subtree is not descended into
    either, since it is judged on its own.
    """
    result: set[int] = set()
    stack = list(children.get(cat_id, []))
    while stack:
        child = stack.pop()
        if child in line_category_ids:
            continue
        result.add(child)
        stack.extend(children.get(child, []))
    return result


# ---------------------------------------------------------------------------
# R1: honest headline (summary block)
# ---------------------------------------------------------------------------


def _compute_summary_inputs(db: Session, budget: Budget, actuals) -> tuple[
    float, float, tuple[IncidentalLabelAmount, ...], float, float
]:
    consumption = sum(
        line.actual for line in actuals.expense_lines if line.category_type != "savings"
    )
    raw_net = actuals.total_actual_income - consumption

    labels = {l.id: l.name for l in db.execute(select(IncidentalLabel)).scalars().all()}

    incidental_tx = db.execute(
        select(Transaction).where(
            Transaction.is_incidental.is_(True),
            Transaction.datum >= budget.start_date,
            Transaction.datum < budget.end_date,
        )
    ).scalars().all()

    by_label: dict[int, float] = {}
    unlabeled = 0.0
    for tx in incidental_tx:
        net = -tx.bedrag  # expense (bedrag<0) adds spend; income (bedrag>0) reduces it
        if tx.incidental_label_id is None:
            unlabeled += net
        else:
            by_label[tx.incidental_label_id] = by_label.get(tx.incidental_label_id, 0.0) + net

    incidental_by_label = tuple(
        IncidentalLabelAmount(label=labels.get(label_id, "Unknown"), amount=_r(amount))
        for label_id, amount in sorted(by_label.items(), key=lambda kv: labels.get(kv[0], ""))
    )
    unlabeled_incidental = _r(unlabeled)
    # Round every displayed part first, then total = sum of the parts, so the
    # incidental breakdown always adds up exactly to incidental_total.
    incidental_total = _r(sum(a.amount for a in incidental_by_label) + unlabeled_incidental)
    structural_net = raw_net + incidental_total

    return _r(raw_net), incidental_total, incidental_by_label, unlabeled_incidental, _r(structural_net)


# ---------------------------------------------------------------------------
# Rule implementations
# ---------------------------------------------------------------------------


def _is_fixed_line(line: BudgetActualLine) -> bool:
    return line.category_type == "expense" and (line.source == "recurring" or line.is_fixed)


def _is_flexible_line(line: BudgetActualLine) -> bool:
    return line.category_type == "expense" and line.source == "manual" and not line.is_fixed


def _r2_fixed_ghost(fixed_lines: list[BudgetActualLine]) -> list[Highlight]:
    highlights = []
    for line in fixed_lines:
        try:
            if line.actual == 0 and line.budgeted > 0:
                highlights.append(Highlight(
                    rule="fixed_ghost",
                    severity=SEVERITY_WARN,
                    title=f"{line.category_name}: no payment occurred",
                    detail=(
                        f"Planned EUR {line.budgeted:.2f}, nothing arrived. "
                        "Check the Recurring page for a stale payment."
                    ),
                    category_id=line.category_id,
                    amount=_r(line.budgeted),
                ))
        except Exception:
            logger.exception("R2 fixed_ghost failed for category %s", getattr(line, "category_id", None))
    return highlights


def _r3_bill_change(fixed_lines: list[BudgetActualLine]) -> list[Highlight]:
    highlights = []
    for line in fixed_lines:
        try:
            if line.budgeted <= 0 or line.actual == 0:
                continue  # actual==0 is R2's ghost, not a bill change
            if line.actual > line.budgeted * BILL_INCREASE_FACTOR:
                diff = line.actual - line.budgeted
                highlights.append(Highlight(
                    rule="bill_change",
                    severity=SEVERITY_INFO,
                    title=f"{line.category_name}: bill increased",
                    detail=(
                        f"This bill came in EUR {diff:.2f} above plan "
                        f"(EUR {line.actual:.2f} vs EUR {line.budgeted:.2f})."
                    ),
                    category_id=line.category_id,
                    amount=_r(diff),
                ))
            elif line.actual < line.budgeted / BILL_INCREASE_FACTOR:
                diff = line.budgeted - line.actual
                highlights.append(Highlight(
                    rule="bill_change",
                    severity=SEVERITY_INFO,
                    title=f"{line.category_name}: bill decreased",
                    detail=(
                        f"This bill came in EUR {diff:.2f} below plan "
                        f"(EUR {line.actual:.2f} vs EUR {line.budgeted:.2f})."
                    ),
                    category_id=line.category_id,
                    amount=_r(diff),
                ))
        except Exception:
            logger.exception("R3 bill_change failed for category %s", getattr(line, "category_id", None))
    return highlights


def _one_off_detail(
    db: Session, budget: Budget, target_cat_ids: set[int], effective_actual: float,
) -> str:
    """Search transactions across target_cat_ids for a single transaction
    whose spend is >= ONE_OFF_FRACTION of the effective (aggregated) actual.
    Returns an extra sentence to append to the overrun detail, or "".

    Reuses `_iter_expense_items` (the same helper `compute_budget_actuals`
    uses) so a receipted, split transaction is attributed the same way here
    as in the actuals: per line item category and amount, not the whole
    transaction `bedrag`. Receipt-less transactions come through as a single
    item at the already offset-adjusted, floor-at-0 amount, again matching
    the actuals computation exactly.
    """
    if effective_actual <= 0 or not target_cat_ids:
        return ""
    last_day = budget.end_date - timedelta(days=1)
    totals: dict[int, float] = {}
    tx_by_id: dict[int, Transaction] = {}
    for item in _iter_expense_items(db, budget.start_date, last_day):
        if item.category_id not in target_cat_ids:
            continue
        totals[item.tx.id] = totals.get(item.tx.id, 0.0) + item.amount
        tx_by_id[item.tx.id] = item.tx
    if not totals:
        return ""
    best_id = max(totals, key=lambda i: totals[i])
    best_amount = totals[best_id]
    if best_amount >= ONE_OFF_FRACTION * effective_actual:
        tx = tx_by_id[best_id]
        merchant = tx.merchant_name or tx.naam or "Unknown"
        return f" Largely one purchase: {merchant} EUR {best_amount:.2f} on {tx.datum.isoformat()}."
    return ""


def _r4_flexible_overrun(
    db: Session, budget: Budget, flexible_lines: list[BudgetActualLine],
    actual_by_cat: dict[int, float], children: dict[int, list[int]], line_category_ids: set[int],
) -> tuple[list[Highlight], set[int]]:
    highlights = []
    flagged: set[int] = set()
    for line in flexible_lines:
        try:
            descendants = _foldable_descendants(line.category_id, children, line_category_ids)
            effective_actual = actual_by_cat.get(line.category_id, 0.0) + sum(
                actual_by_cat.get(d, 0.0) for d in descendants
            )
            threshold = max(line.budgeted * OVERRUN_PCT, OVERRUN_MIN_EUR)
            if effective_actual - line.budgeted > threshold:
                flagged.add(line.category_id)
                diff = effective_actual - line.budgeted
                detail = (
                    f"EUR {effective_actual:.2f} spent vs EUR {line.budgeted:.2f} planned "
                    f"(EUR {diff:.2f} over)."
                )
                detail += _one_off_detail(
                    db, budget, {line.category_id} | descendants, effective_actual
                )
                highlights.append(Highlight(
                    rule="flexible_overrun",
                    severity=SEVERITY_WARN,
                    title=f"{line.category_name}: over plan",
                    detail=detail,
                    category_id=line.category_id,
                    amount=_r(diff),
                ))
        except Exception:
            logger.exception("R4 flexible_overrun failed for category %s", getattr(line, "category_id", None))
    return highlights, flagged


def _r5_flexible_underrun(
    flexible_lines: list[BudgetActualLine], actual_by_cat: dict[int, float],
    children: dict[int, list[int]], line_category_ids: set[int],
) -> list[Highlight]:
    best: Opt[Highlight] = None
    best_unspent = -1.0
    for line in flexible_lines:
        try:
            if line.budgeted <= 0:
                continue
            descendants = _foldable_descendants(line.category_id, children, line_category_ids)
            effective_actual = actual_by_cat.get(line.category_id, 0.0) + sum(
                actual_by_cat.get(d, 0.0) for d in descendants
            )
            if effective_actual < line.budgeted * UNDERRUN_FRACTION:
                unspent = line.budgeted - effective_actual
                if unspent > best_unspent:
                    best_unspent = unspent
                    best = Highlight(
                        rule="flexible_underrun",
                        severity=SEVERITY_INFO,
                        title=f"{line.category_name}: well under plan",
                        detail=(
                            f"EUR {effective_actual:.2f} spent vs EUR {line.budgeted:.2f} planned "
                            f"(EUR {unspent:.2f} unspent)."
                        ),
                        category_id=line.category_id,
                        amount=_r(unspent),
                    )
        except Exception:
            logger.exception("R5 flexible_underrun failed for category %s", getattr(line, "category_id", None))
    return [best] if best else []


def _r6_savings_execution(
    db: Session, budget: Budget, savings_lines: list[BudgetActualLine], closed: bool,
) -> tuple[list[Highlight], int, int]:
    highlights = []
    pots_planned = 0
    pots_executed = 0
    all_funded = True
    for line in savings_lines:
        try:
            if line.budgeted <= 0:
                continue
            pots_planned += 1
            contributed = line.actual
            if contributed >= line.budgeted:
                pots_executed += 1
                continue  # good cards are suppressed; see aggregate below
            all_funded = False
            if contributed == 0:
                severity = SEVERITY_WARN if closed else SEVERITY_INFO
                framing = "" if closed else " yet"
                highlights.append(Highlight(
                    rule="savings_no_transfer",
                    severity=severity,
                    title=f"{line.category_name}: no transfer categorized",
                    detail=(
                        f"No transfer categorized to this pot{framing}: either it was not made, "
                        "or the transaction is not categorized yet."
                    ),
                    category_id=line.category_id,
                    amount=0.0,
                ))
            elif contributed < 0:
                withdrawals = db.execute(
                    select(Transaction).where(
                        Transaction.category_id == line.category_id,
                        Transaction.is_internal_transfer.is_(True),
                        Transaction.bedrag > 0,
                        Transaction.datum >= budget.start_date,
                        Transaction.datum < budget.end_date,
                    ).order_by(Transaction.bedrag.desc())
                ).scalars().all()[:3]
                listing = "; ".join(
                    f"{tx.datum.isoformat()} EUR {tx.bedrag:.2f} {tx.naam or 'Unknown'}"
                    for tx in withdrawals
                )
                detail = f"Net withdrawal of EUR {abs(contributed):.2f}."
                if listing:
                    detail += f" Recent withdrawals: {listing}."
                highlights.append(Highlight(
                    rule="savings_withdrawal",
                    severity=SEVERITY_WARN,
                    title=f"{line.category_name}: net withdrawal",
                    detail=detail,
                    category_id=line.category_id,
                    amount=_r(abs(contributed)),
                ))
            else:
                highlights.append(Highlight(
                    rule="savings_partial",
                    severity=SEVERITY_INFO,
                    title=f"{line.category_name}: partially funded",
                    detail=(
                        f"Partially funded: EUR {contributed:.2f} of EUR {line.budgeted:.2f}."
                    ),
                    category_id=line.category_id,
                    amount=_r(line.budgeted - contributed),
                ))
        except Exception:
            logger.exception("R6 savings_execution failed for category %s", getattr(line, "category_id", None))
            all_funded = False

    if pots_planned > 0 and all_funded:
        highlights.append(Highlight(
            rule="savings_funded",
            severity=SEVERITY_GOOD,
            title="All savings pots funded",
            detail=(
                f"All {pots_planned} planned savings pots received at least their planned "
                "contribution this period."
            ),
            category_id=None,
            amount=0.0,
        ))

    return highlights, pots_planned, pots_executed


def _r7_income_change(income_lines: list[BudgetActualLine]) -> list[Highlight]:
    highlights = []
    for line in income_lines:
        try:
            if line.budgeted <= 0 or line.actual <= 0:
                continue
            diff = line.actual - line.budgeted
            if abs(diff) > line.budgeted * SALARY_CHANGE_PCT:
                up = diff > 0
                highlights.append(Highlight(
                    rule="income_change",
                    severity=SEVERITY_GOOD if up else SEVERITY_INFO,
                    title=f"{line.category_name}: income {'up' if up else 'down'}",
                    detail=(
                        f"Income came in EUR {abs(diff):.2f} {'above' if up else 'below'} plan "
                        f"(EUR {line.actual:.2f} vs EUR {line.budgeted:.2f})."
                    ),
                    category_id=line.category_id,
                    amount=_r(diff),
                ))
        except Exception:
            logger.exception("R7 income_change failed for category %s", getattr(line, "category_id", None))
    return highlights


def _r8_top_expenses(db: Session, budget: Budget, categories: dict[int, CategoryModel]) -> list[Highlight]:
    try:
        rows = db.execute(
            select(Transaction).where(
                Transaction.bedrag < 0,
                Transaction.is_incidental.is_(False),
                Transaction.is_internal_transfer.is_(False),
                Transaction.datum >= budget.start_date,
                Transaction.datum < budget.end_date,
            )
        ).scalars().all()
        if not rows:
            return []
        ranked = sorted(rows, key=lambda tx: (-abs(tx.bedrag), tx.datum, tx.id))
        top = ranked[:TOP_EXPENSES_COUNT]
        entries = []
        for i, tx in enumerate(top, start=1):
            merchant = tx.merchant_name or tx.naam or "Unknown"
            cat_name = full_category_path(tx.category_id, categories) if tx.category_id else "Uncategorized"
            entries.append(f"{i}. {merchant} EUR {abs(tx.bedrag):.2f} on {tx.datum.isoformat()} ({cat_name})")
        return [Highlight(
            rule="top_expenses",
            severity=SEVERITY_INFO,
            title="Top expenses",
            detail="; ".join(entries),
            category_id=None,
            amount=_r(sum(abs(tx.bedrag) for tx in top)),
        )]
    except Exception:
        logger.exception("R8 top_expenses failed for budget %s", budget.id)
        return []


def _r9_scorecard(
    flexible_total: int, flexible_within_plan: int, pots_executed: int, pots_planned: int,
) -> list[Highlight]:
    return [Highlight(
        rule="scorecard",
        severity=SEVERITY_INFO,
        title="Scorecard",
        detail=(
            f"{flexible_within_plan} of {flexible_total} flexible categories within plan; "
            f"savings plan {pots_executed} of {pots_planned} pots executed."
        ),
        category_id=None,
        amount=0.0,
    )]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def compute_highlights(
    db: Session,
    budget: Budget,
    today: date | None = None,
    prior_overruns: set[int] | None = None,
) -> HighlightsResult:
    """Pure function: same actuals/transactions in, same highlights out.

    `today` is injectable for tests; defaults to the real current date.
    `prior_overruns` is R10's seam (climate detection, deferred to v1.1):
    accepted but not read by any rule yet.
    """
    if today is None:
        today = date.today()
    closed = budget.end_date <= today

    actuals = compute_budget_actuals(db, budget)

    raw_net, incidental_total, incidental_by_label, unlabeled_incidental, structural_net = (
        _compute_summary_inputs(db, budget, actuals)
    )

    all_cats = db.execute(select(CategoryModel)).scalars().all()
    categories = {c.id: c for c in all_cats}
    children = _children_map(all_cats)
    line_category_ids = {l.category_id for l in budget.lines}

    actual_by_cat = {line.category_id: line.actual for line in actuals.expense_lines}

    fixed_lines = [l for l in actuals.expense_lines if _is_fixed_line(l)]
    flexible_lines = [
        l for l in actuals.expense_lines if _is_flexible_line(l) and l.category_id in line_category_ids
    ]
    savings_lines = [l for l in actuals.expense_lines if l.category_type == "savings"]

    highlights: list[Highlight] = []
    flexible_total = len(flexible_lines)
    flagged_overrun: set[int] = set()

    if closed:
        highlights.extend(_r2_fixed_ghost(fixed_lines))
        highlights.extend(_r3_bill_change(fixed_lines))
        r4_highlights, flagged_overrun = _r4_flexible_overrun(
            db, budget, flexible_lines, actual_by_cat, children, line_category_ids
        )
        highlights.extend(r4_highlights)
        highlights.extend(_r5_flexible_underrun(flexible_lines, actual_by_cat, children, line_category_ids))

    r6_highlights, pots_planned, pots_executed = _r6_savings_execution(db, budget, savings_lines, closed)
    highlights.extend(r6_highlights)
    highlights.extend(_r7_income_change(actuals.income_lines))
    highlights.extend(_r8_top_expenses(db, budget, categories))

    flexible_within_plan = flexible_total - len(flagged_overrun)
    if closed:
        highlights.extend(_r9_scorecard(flexible_total, flexible_within_plan, pots_executed, pots_planned))

    highlights.sort(key=lambda h: (
        RULE_ORDER.get(h.rule, 99),
        -abs(h.amount or 0.0),
        h.category_id if h.category_id is not None else -1,
    ))

    summary = HighlightsSummary(
        raw_net=raw_net,
        incidental_total=incidental_total,
        incidental_by_label=incidental_by_label,
        unlabeled_incidental=unlabeled_incidental,
        structural_net=structural_net,
        flexible_within_plan=flexible_within_plan,
        flexible_total=flexible_total,
        pots_executed=pots_executed,
        pots_planned=pots_planned,
    )

    return HighlightsResult(
        budget_id=budget.id,
        start_date=budget.start_date,
        end_date=budget.end_date,
        closed=closed,
        summary=summary,
        highlights=tuple(highlights),
    )
