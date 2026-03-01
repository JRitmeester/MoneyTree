# Zero-Based Budget Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current budget page with a zero-based budget planner that separates fixed recurring costs from flexible discretionary allocations, powered by a reusable template.

**Architecture:** New `BudgetTemplate` table + `is_fixed` flag on `Category`. Monthly budgets auto-create from the template with per-month override support. Frontend gets a complete rewrite with two tabs (Plan / Actuals) and a two-column layout (fixed left, flexible right).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, SvelteKit 2, Svelte 5, TypeScript

---

## Task 1: Database Migration — Add `is_fixed` to Category + Create `BudgetTemplate` table

**Files:**
- Modify: `backend/app/models.py:108-120` (Category model)
- Create: `backend/alembic/versions/<auto>_add_budget_template.py`

**Step 1: Add `is_fixed` column to Category model**

In `backend/app/models.py`, add after line 114 (`is_bank_category`):

```python
is_fixed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

**Step 2: Add BudgetTemplate model**

In `backend/app/models.py`, add after the `BudgetLine` class (after line 170):

```python
class BudgetTemplate(Base):
    __tablename__ = "budget_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), unique=True, nullable=False
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)

    category: Mapped["Category"] = relationship()
```

**Step 3: Generate Alembic migration**

Run from project root:
```bash
cd /Users/jeroenrit.meester/Programming/MoneyTree && python -m alembic -c backend/alembic.ini revision --autogenerate -m "add_budget_template_and_is_fixed"
```

Expected: Creates a new migration file in `backend/alembic/versions/`.

**Step 4: Review the generated migration**

Open the new file and verify it contains:
- `batch_op.add_column(sa.Column('is_fixed', sa.Boolean(), nullable=False, server_default='0'))` on `categories`
- `op.create_table('budget_templates', ...)` with `id`, `category_id` (unique), `amount`

**Step 5: Run the migration**

```bash
cd /Users/jeroenrit.meester/Programming/MoneyTree && python -m alembic -c backend/alembic.ini upgrade head
```

Expected: Migration applies cleanly.

**Step 6: Verify the backend starts**

```bash
cd /Users/jeroenrit.meester/Programming/MoneyTree/backend && python -m uvicorn app.main:app --port 8080
```

Expected: Server starts without errors. Stop it after verifying.

**Step 7: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/
git commit -m "feat: add BudgetTemplate model and is_fixed flag on Category"
```

---

## Task 2: Update Pydantic Schemas

**Files:**
- Modify: `backend/app/schemas.py`

**Step 1: Add `is_fixed` to CategoryOut and CategoryCreate**

In `backend/app/schemas.py`, modify `CategoryOut` (around line 158) to add:

```python
class CategoryOut(BaseModel):
    id: int
    name: str
    parent_id: Optional[int]
    is_bank_category: bool
    is_fixed: bool
    category_type: str
    children: list["CategoryOut"] = []

    model_config = {"from_attributes": True}
```

Modify `CategoryCreate` (around line 169) to add `is_fixed`:

```python
class CategoryCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None
    category_type: str = "expense"
    is_fixed: bool = False
```

**Step 2: Add BudgetTemplate schemas**

Add after the existing Budget schemas (after `BudgetUpdate`, around line 297):

```python
# --- Budget Template ---


class BudgetTemplateLineOut(BaseModel):
    id: int
    category_id: int
    category_name: str
    category_type: str
    is_fixed: bool
    amount: float

    model_config = {"from_attributes": True}


class BudgetTemplateOut(BaseModel):
    lines: list[BudgetTemplateLineOut]
    total_income: float
    total_fixed_expenses: float
    discretionary: float
    total_flexible_expenses: float
    unallocated: float


class BudgetTemplateLineCreate(BaseModel):
    category_id: int
    amount: float
```

**Step 3: Modify BudgetLineOut to include template-awareness**

Replace the existing `BudgetLineOut` (around line 253):

```python
class BudgetLineOut(BaseModel):
    id: int
    category_id: int
    category_name: str
    category_type: str
    is_fixed: bool
    amount: float
    is_overridden: bool = False
    template_amount: float = 0.0

    model_config = {"from_attributes": True}
```

**Step 4: Commit**

```bash
git add backend/app/schemas.py
git commit -m "feat: add budget template schemas and is_fixed to category schemas"
```

---

## Task 3: Budget Template API Endpoints

**Files:**
- Create: `backend/app/routers/budget_template.py`
- Modify: `backend/app/main.py:12,41`

**Step 1: Create the budget template router**

Create `backend/app/routers/budget_template.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import BudgetTemplate, Category
from ..schemas import BudgetTemplateLineCreate, BudgetTemplateLineOut, BudgetTemplateOut

router = APIRouter(prefix="/api/budget-template", tags=["budget-template"])


def _build_template_response(db: Session) -> BudgetTemplateOut:
    templates = db.execute(
        select(BudgetTemplate).order_by(BudgetTemplate.id)
    ).scalars().all()

    lines = []
    total_income = 0.0
    total_fixed_expenses = 0.0
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
        elif cat.is_fixed:
            total_fixed_expenses += t.amount
        else:
            total_flexible_expenses += t.amount

    discretionary = total_income - total_fixed_expenses
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
    db.execute(select(BudgetTemplate)).scalars()
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
```

**Step 2: Register the router in main.py**

In `backend/app/main.py`, add the import (line 12):

Change:
```python
from .routers import budget, categories, category_mappings, dashboard, line_items, receipts, transactions
```
To:
```python
from .routers import budget, budget_template, categories, category_mappings, dashboard, line_items, receipts, transactions
```

Add after `app.include_router(budget.router)` (after line 41):
```python
app.include_router(budget_template.router)
```

**Step 3: Test the endpoint manually**

```bash
cd /Users/jeroenrit.meester/Programming/MoneyTree/backend && python -m uvicorn app.main:app --port 8080 &
sleep 2
curl -s http://localhost:8080/api/budget-template | python3 -m json.tool
kill %1
```

Expected: Returns `{"lines": [], "total_income": 0.0, "total_fixed_expenses": 0.0, "discretionary": 0.0, "total_flexible_expenses": 0.0, "unallocated": 0.0}`

**Step 4: Commit**

```bash
git add backend/app/routers/budget_template.py backend/app/main.py
git commit -m "feat: add budget template API endpoints (GET, PUT, PATCH)"
```

---

## Task 4: Modify Budget Router — Auto-Create from Template + Override Tracking

**Files:**
- Modify: `backend/app/routers/budget.py`

**Step 1: Rewrite the budget router**

Replace the entire contents of `backend/app/routers/budget.py`:

```python
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
    """Update a budget (replaces all lines). Optionally updates template too."""
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
```

**Step 2: Verify the backend starts and endpoints work**

```bash
cd /Users/jeroenrit.meester/Programming/MoneyTree/backend && python -m uvicorn app.main:app --port 8080
```

Test: `GET /api/budgets` should still return existing budgets.

**Step 3: Commit**

```bash
git add backend/app/routers/budget.py
git commit -m "feat: budget auto-creates from template, tracks overrides"
```

---

## Task 5: Update Categories Router — Accept `is_fixed`

**Files:**
- Modify: `backend/app/routers/categories.py:47-60`

**Step 1: Update the PATCH endpoint to handle is_fixed**

In `backend/app/routers/categories.py`, modify the `update_category` function (line 47-60). After `cat.category_type = data.category_type` (line 57), add:

```python
    cat.is_fixed = data.is_fixed
```

Also update the `create_category` function to pass `is_fixed` through. After `category_type=data.category_type,` (line 39), add:

```python
        is_fixed=data.is_fixed,
```

**Step 2: Commit**

```bash
git add backend/app/routers/categories.py
git commit -m "feat: categories CRUD now supports is_fixed flag"
```

---

## Task 6: Add `is_fixed` to BudgetVsActualLine Schema

**Files:**
- Modify: `backend/app/schemas.py` (BudgetVsActualLine)
- Modify: `backend/app/routers/dashboard.py:366-490`

**Step 1: Add is_fixed to BudgetVsActualLine**

In `backend/app/schemas.py`, modify `BudgetVsActualLine` (around line 303):

```python
class BudgetVsActualLine(BaseModel):
    category_id: int
    category_name: str
    category_type: str
    is_fixed: bool
    budgeted: float
    actual: float
    difference: float
    percentage: float
```

**Step 2: Pass is_fixed in the dashboard endpoint**

In `backend/app/routers/dashboard.py`, in the `get_budget_vs_actual` function, modify the `BudgetVsActualLine` construction (around line 453). Add `is_fixed=cat.is_fixed`:

Change:
```python
        line = BudgetVsActualLine(
            category_id=cat_id,
            category_name=cat.name,
            category_type=cat.category_type,
            budgeted=budgeted,
            actual=actual,
            difference=difference,
            percentage=percentage,
        )
```

To:
```python
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
```

**Step 3: Commit**

```bash
git add backend/app/schemas.py backend/app/routers/dashboard.py
git commit -m "feat: budget-vs-actual includes is_fixed per category"
```

---

## Task 7: Frontend API Functions

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Step 1: Add template types and API functions**

Add after the existing Budget types (after `BudgetVsActualSummary` interface, around line 513):

```typescript
// --- Budget Template ---

export interface BudgetTemplateLine {
	id: number;
	category_id: number;
	category_name: string;
	category_type: string;
	is_fixed: boolean;
	amount: number;
}

export interface BudgetTemplate {
	lines: BudgetTemplateLine[];
	total_income: number;
	total_fixed_expenses: number;
	discretionary: number;
	total_flexible_expenses: number;
	unallocated: number;
}

export async function getBudgetTemplate(): Promise<BudgetTemplate> {
	return request('/api/budget-template');
}

export async function replaceBudgetTemplate(lines: { category_id: number; amount: number }[]): Promise<BudgetTemplate> {
	return request('/api/budget-template', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(lines),
	});
}
```

**Step 2: Update existing budget types for template-awareness**

Modify the `BudgetLine` interface (inside `Budget`). Add `is_fixed`, `is_overridden`, `template_amount` to the `BudgetLine` interface:

```typescript
export interface BudgetLine {
	id: number;
	category_id: number;
	category_name: string;
	category_type: string;
	is_fixed: boolean;
	amount: number;
	is_overridden: boolean;
	template_amount: number;
}
```

Note: The current code doesn't have a separate `BudgetLine` interface — the `Budget` interface uses `lines: BudgetLine[]` where `BudgetLine` is defined elsewhere. Check the existing types and add/update the `BudgetLine` interface. The existing `BudgetVsActualLine` also needs `is_fixed: boolean` added.

**Step 3: Update the `updateBudget` function to accept `update_template` parameter**

Modify the existing `updateBudget` function:

```typescript
export async function updateBudget(year: number, month: number, data: { lines: { category_id: number; amount: number }[] }, updateTemplate: boolean = false): Promise<Budget> {
	const qs = updateTemplate ? '?update_template=true' : '';
	return request(`/api/budgets/${year}/${month}${qs}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data),
	});
}
```

**Step 4: Add `is_fixed` to Category interface**

Find the `Category` interface and add `is_fixed: boolean`.

**Step 5: Remove unused functions**

Remove `createBudget` and `copyBudget` functions — they're no longer needed.

**Step 6: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: frontend API types and functions for budget template"
```

---

## Task 8: Frontend Budget Page — Complete Rewrite

**Files:**
- Modify: `frontend/src/routes/budget/+page.svelte` (complete rewrite)

This is the largest task. The page is completely rewritten with:
- Two tabs: Plan and Actuals
- Two-column layout on Plan tab (left: fixed income/expenses, right: flexible)
- Summary banner with key totals
- Inline editing with template awareness
- Actuals tab using the existing budget-vs-actual data

**Step 1: Rewrite the budget page**

Replace the entire contents of `frontend/src/routes/budget/+page.svelte` with the new implementation. The key structure:

```svelte
<script lang="ts">
	// Imports: getBudget, getBudgetTemplate, updateBudget, replaceBudgetTemplate,
	//          getBudgetVsActual, getCategories, formatEuro
	// State: currentYear, currentMonth, activeTab ('plan' | 'actuals')
	// State: template, budget, bvaData, categories
	// State: editing, editLines
	// Derived: fixedIncomeLines, fixedExpenseLines, flexibleExpenseLines
	// Derived: totalIncome, totalFixedExpenses, discretionary, totalFlexible, unallocated
	// Functions: load(), prevMonth(), nextMonth(), startEditing(), saveEditing()
</script>

<!-- Tab bar: Plan | Actuals -->
<!-- Month navigation -->

{#if activeTab === 'plan'}
	<!-- Summary banner: Income | Fixed | Discretionary | Allocated | Unallocated -->
	<!-- Two-column layout -->
	<!-- Left: Fixed Income section + Fixed Expenses section + Discretionary subtotal -->
	<!-- Right: Flexible Expenses section + Allocated/Unallocated subtotals -->
	<!-- Edit mode: inline amount editing + "Update template" checkbox -->
	<!-- No template state: onboarding prompt -->
{:else}
	<!-- Actuals tab: reuse existing budget-vs-actual view -->
	<!-- Group by is_fixed: Fixed section (checkmark style) + Flexible section (progress bars) -->
{/if}
```

The full implementation should:

1. **Load data**: Fetch template, budget (auto-created from template), budget-vs-actual, categories in parallel
2. **Plan tab (view mode)**: Display the two-column layout as described in the design. Left column shows fixed income at top, fixed expenses below, with a "Discretionary" subtotal. Right column shows flexible expenses with "Allocated" and "Unallocated" subtotals. Use the budget data (which comes from the template for new months).
3. **Plan tab (edit mode)**: Each amount becomes an input field. An "Update template too?" checkbox (default checked) appears. Add/remove lines with category picker. Save sends PUT to budget endpoint with `update_template` query param.
4. **No template onboarding**: If template is empty and no budget exists, show a setup prompt instead of the two-column view. Direct user to start adding income and expense lines.
5. **Actuals tab**: Existing budget-vs-actual view, but reorganized: fixed categories in one section (simple: budgeted vs actual, checkmark if within range), flexible categories in another (with progress bars). Summary cards at top.
6. **Styling**: Reuse existing color scheme (#2d6a4f green, #dc2626 red, white cards, #e5e7eb borders). Two-column layout uses CSS grid. Responsive: stack columns on mobile.

**Step 2: Test manually in browser**

Navigate to `http://localhost:8080/budget`. Verify:
- Plan tab shows two-column layout (or onboarding if no template)
- Can switch to Actuals tab
- Month navigation works
- Edit mode allows changing amounts
- "Update template" checkbox works
- Summary banner updates reactively

**Step 3: Commit**

```bash
git add frontend/src/routes/budget/+page.svelte
git commit -m "feat: rewrite budget page with zero-based two-column layout"
```

---

## Task 9: Integration Testing & Polish

**Files:**
- Various files from previous tasks

**Step 1: End-to-end flow test**

Test the full flow manually:
1. Go to `/budget` — should show onboarding (no template yet)
2. Click edit, add income category (Salary, mark as fixed in categories first), set to €3200
3. Add fixed expense categories (Rent €850, Insurance €120, etc.)
4. Add flexible expense categories (Groceries €400, etc.)
5. Save with "Update template" checked
6. Navigate to next month — should auto-create from template
7. Override one amount for the month (without updating template)
8. Navigate back — override should be visible
9. Switch to Actuals tab — should show budget-vs-actual comparison

**Step 2: Fix any issues found during testing**

Address UI polish, edge cases, responsive layout issues.

**Step 3: Build the frontend to verify no TypeScript errors**

```bash
cd /Users/jeroenrit.meester/Programming/MoneyTree/frontend && npm run build
```

Expected: Build succeeds with no errors.

**Step 4: Final commit**

```bash
git add -A
git commit -m "fix: integration testing polish for zero-based budget"
```

---

## Summary of Commits

1. `feat: add BudgetTemplate model and is_fixed flag on Category` (migration + models)
2. `feat: add budget template schemas and is_fixed to category schemas` (Pydantic)
3. `feat: add budget template API endpoints (GET, PUT, PATCH)` (new router)
4. `feat: budget auto-creates from template, tracks overrides` (budget router rewrite)
5. `feat: categories CRUD now supports is_fixed flag` (categories router)
6. `feat: budget-vs-actual includes is_fixed per category` (dashboard + schema)
7. `feat: frontend API types and functions for budget template` (api.ts)
8. `feat: rewrite budget page with zero-based two-column layout` (page rewrite)
9. `fix: integration testing polish for zero-based budget` (final polish)
