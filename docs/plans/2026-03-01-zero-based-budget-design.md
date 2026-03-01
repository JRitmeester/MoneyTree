# Zero-Based Budget Redesign - Design

## Problem

The current budget page reconstructs budgets from imported transactions and compares actuals against budgeted amounts. This is backward-looking. The user wants a forward-looking budgeting tool that starts with known income, subtracts fixed recurring costs, and then allocates the remaining "discretionary" money to flexible categories until every euro has a job (zero-based budgeting).

## Solution

Replace the budget page with a zero-based budget planner. A template defines the user's standard monthly budget. Monthly budgets are auto-created from the template and can be overridden per-month. The page has two tabs: **Plan** (the budget builder) and **Actuals** (budget-vs-actual comparison).

## Key Concepts (from personal finance / accounting)

- **Zero-based budgeting**: Every euro of income is assigned to a category. Income minus all allocations equals zero.
- **Fixed expenses**: Recurring, predictable costs (rent, insurance, gym) that rarely change month to month.
- **Flexible/discretionary expenses**: Variable spending (groceries, entertainment) allocated from what remains after fixed costs.
- **Discretionary income**: Total income minus fixed expenses. This is the pool available for flexible allocations. Sometimes called "free to spend" or "ready to assign" (YNAB terminology).

## Data Model Changes

### Modified: `Category` table

Add column:
- `is_fixed: bool = False` — Marks categories as fixed (rent, insurance) vs flexible (groceries, fun). Set in category management.

### New: `BudgetTemplate` table

```
BudgetTemplate
  id          (PK, autoincrement)
  category_id (FK → Category, unique)
  amount      (float)
```

One row per category that has a budgeted amount. Represents the user's standard monthly budget. Both income and expense categories can appear here.

### Unchanged: `Budget` / `BudgetLine` tables

Their role shifts:
- A monthly `Budget` is auto-created from the template when a month is first viewed.
- `BudgetLine.amount` can override the template amount for that specific month.
- If all lines match the template, the month has no overrides.

## Page Layout

The budget page (`/budget`) has two tabs: **Plan** and **Actuals**.

### Plan Tab

**Top bar:** Month navigation (left/right arrows) + "Edit" button

**Summary banner:**
```
Total Income: €3,200 | Fixed Expenses: €1,220 | Discretionary: €1,980 | Allocated: €1,025 | Unallocated: €955
```
"Unallocated" is color-coded: green at €0 (balanced), orange/red when positive (money to assign) or negative (over-allocated).

**Two-column layout:**

```
┌─────────────────────────────┬──────────────────────────────┐
│  INCOME (Fixed)             │  FLEXIBLE EXPENSES           │
│  Salary           €3,200   │  Groceries          €400    │
│                             │  Car                €150    │
│  FIXED EXPENSES             │  Savings            €300    │
│  Rent               €850   │  Fun                €100    │
│  Insurance          €120   │  Clothing            €75    │
│  Gym                 €40   │                              │
│  Energy             €180   │                              │
│  Water               €30   │                              │
│  ─────────────────────────  │  ──────────────────────────  │
│  Discretionary:    €1,980   │  Allocated:        €1,025   │
│                             │  Unallocated:        €955   │
└─────────────────────────────┴──────────────────────────────┘
```

- **Left column**: Fixed income at top, fixed expenses below. Subtotal shows "Discretionary" (income minus fixed expenses).
- **Right column**: Flexible expense categories with allocated amounts. Subtotal shows total allocated and remaining unallocated.
- The two subtotals are linked: left column's "Discretionary" minus right column's "Allocated" = "Unallocated".

### Edit Mode

Inline editing — click an amount to change it. Add/remove lines with + button.

When editing an amount:
- Checkbox "Update template too?" (default: checked). Updates both the current month and the template for future months.
- Lines that differ from the template show an "overridden" indicator.
- "Reset to template" available per-line or for the whole budget.

### Actuals Tab

The existing budget-vs-actual comparison, reorganized to match the fixed/flexible grouping:
- Fixed categories shown with checkmark (paid/not paid) since they're predictable.
- Flexible categories shown with progress bars (spent vs budgeted).
- Summary shows actual remaining discretionary vs planned.

## Template Management

- Template is edited through the Plan tab itself (no separate template page).
- Navigating to a month with no budget auto-creates it from the template.
- If no template exists (first use), show onboarding: "Set up your budget template."
- "Reset to template" reverts month-specific overrides.

## API Changes

### New endpoints

```
GET    /api/budget-template              → list all template lines (grouped by is_fixed + type)
PUT    /api/budget-template              → replace all template lines
PATCH  /api/budget-template/{line_id}    → update single template line amount
```

### Modified endpoints

```
GET    /api/budgets/{year}/{month}       → auto-creates from template if budget doesn't exist
                                            response includes is_overridden flag per line
                                            response includes template_amount per line
PATCH  /api/categories/{id}              → now accepts is_fixed field
GET    /api/categories                   → response includes is_fixed
```

### Removed endpoints

```
POST   /api/budgets                      → replaced by auto-creation from template
POST   /api/budgets/{y}/{m}/copy-from/{sy}/{sm} → replaced by template mechanism
```

## Schema Changes (Pydantic)

### New models

```python
class BudgetTemplateLineOut(BaseModel):
    id: int
    category_id: int
    category_name: str
    category_type: str  # "income" or "expense"
    is_fixed: bool
    amount: float

class BudgetTemplateOut(BaseModel):
    lines: list[BudgetTemplateLineOut]
    total_income: float
    total_fixed_expenses: float
    discretionary: float
    total_flexible_expenses: float
    unallocated: float
```

### Modified models

```python
class BudgetLineOut(BaseModel):
    # ... existing fields ...
    is_fixed: bool          # from category
    is_overridden: bool     # differs from template?
    template_amount: float  # original template amount
```

## Migration

### Database (Alembic)

1. Add `is_fixed` column to `categories` table (bool, default False)
2. Create `budget_templates` table (id, category_id unique FK, amount)

### Data

- No automatic migration of existing budget data to templates.
- Existing monthly budgets continue to display on the Actuals tab.
- User creates the template from scratch on first visit (one-time setup).

## File Changes

### New files

```
backend/app/routers/budget_template.py    # Template CRUD endpoints
```

### Modified files

```
backend/app/models.py                     # Add is_fixed to Category, add BudgetTemplate model
backend/app/schemas.py                    # New template schemas, modify BudgetLineOut
backend/app/routers/budget.py             # Auto-create from template, add override tracking
backend/app/routers/categories.py         # Accept is_fixed in PATCH
backend/app/main.py                       # Register budget_template router
backend/alembic/versions/                 # New migration
frontend/src/routes/budget/+page.svelte   # Complete rewrite - two tabs, two-column layout
frontend/src/lib/api.ts                   # Template API functions, updated budget types
```

### Removed

```
POST /api/budgets create endpoint (logic replaced by auto-create)
POST /api/budgets copy-from endpoint (replaced by template)
```
