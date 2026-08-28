# Derived Budget Lines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Budget Fixed/Savings lines derive automatically from confirmed recurring payments and allocation buckets (materialized rows with a `source` column), ending double bookkeeping; manual lines remain wherever no authoritative data exists.

**Architecture:** New pure-ish service `budget_derivation.py` computes target derived lines per budget period and upserts them; budget router calls it lazily on read/create/update for periods with `end_date >= today`. Budget update endpoint restructured to replace manual rows only. Frontend renders derived rows read-only with source badges; Recurring page nudges category linking.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + pytest; SvelteKit + Svelte 5.

**Spec:** docs/superpowers/specs/2026-08-28-derived-budget-lines-design.md is binding; it overrides this plan on conflict.

## Global Constraints

- No em-dashes. Conventional commits, no attribution. TDD with RED evidence.
- Backend baseline 369 tests stays green; svelte-check 0/0; the 7 known uncategorized.test.ts failures untouched. `rtk proxy` for pytest/vitest.
- Alembic head is p6q7r8s9t0u1; new migration chains from it, single head after.
- Budget period date convention is half-open `[start_date, end_date)` (matches `_check_overlap` semantics).
- Local only until the controller merges; no push, no deploy.

---

### Task 1: Migration + derivation service

**Files:** `backend/app/models.py` (BudgetLine gains `source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)`); new migration `q7r8s9t0u1v2` (add column, `server_default='manual'`); new `backend/app/services/budget_derivation.py`; tests: new `backend/tests/test_budget_derivation.py`.

**Interfaces (produces):** `refresh_derived_lines(db: Session, budget: Budget, today: date | None = None) -> None` (no commit; caller owns the transaction). Also a small refactor in `backend/app/services/salary_allocator.py`: extract the waterfall so it can be computed for an arbitrary payday and salary amount: `compute_allocation_at(db, buffer_pct, anchor: date, salary_amount: float) -> SalaryAllocation` (or equivalent keyword args on `compute_allocation`), with `compute_allocation` delegating to it; existing 11 allocator tests stay green unchanged.

**Contract (spec sections "Core mechanism", "Refresh rules", both "Derivation" sections):** No-op when `budget.end_date < today`. Fixed targets: confirmed non-income recurring payments with `category_id`, occurrences via `occurrences_in_range(payment, start_date, end_date, shift_weekend=True)`, per-category sum of `abs(expected_amount)`, stored positive, source "recurring". Savings targets: active buckets with `category_id`; paydays in period = actual salary occurrence dates in `[start, end)`, else projected shifted paydays via `occurrences_in_range(salary, ...)`; per payday compute the waterfall at that payday (actual occurrence amount when the payday is an occurrence, else `expected_amount`) and take the bucket's line amount; per-category sum, source "allocation". Precedence when both derive one category: `category_type == "savings"` prefers allocation, else recurring. Upsert semantics: existing line (manual or derived) for a deriving category gets amount overwritten and source set (one-way adoption); missing line created; stale rows with `source != "manual"` whose category no longer derives are deleted; manual rows otherwise untouched. Per-payment/bucket derivation errors are caught, logged, and skipped (refresh never raises). Buffer pct via the cashflow router's `get_buffer_pct` logic (import the helper or duplicate the two-line read; check first).

- [ ] TDD (RED first) covering: monthly fixed derivation; four-weekly double occurrence in one period; yearly in-month vs out-of-month; uncategorized payment ignored; fixed bucket per payday; percent bucket uses that period's actual salary amount; projected payday fallback uses expected amount; inactive/unlinked buckets ignored; no confirmed salary derives no savings lines; manual-line adoption flips source and amount exactly once (idempotent double refresh); stale derived line removed when payment loses its category; past period (end_date < today) untouched; savings-vs-expense precedence.
- [ ] Implement; verify migration applies on a fresh DB (`alembic upgrade head` in the worktree); full suite; commit `feat(budget): derived-line service and source column`.

### Task 2: Budget router integration

**Files:** `backend/app/routers/budget.py`; `backend/app/schemas.py` (`BudgetLineOut` gains `source: str = "manual"`). Tests: new `backend/tests/test_budget_api.py` (no budget test file exists yet; cover the new behavior, not a retrofit of the whole router).

**Contract (spec "API and validation"):** `get_budget`, `list_budgets`, `create_budget` (after `_create_from_template`), and `update_budget` call `refresh_derived_lines` (list: only for budgets with `end_date >= today`) and commit. `_create_from_template` skips template lines whose category would currently derive (compute the deriving-category set via the service; expose a helper `deriving_category_ids(db, budget) -> dict[int, str]` from Task 1 if cleaner). `update_budget` restructure: delete only lines with `source == "manual"`; ignore payload entries whose category is currently deriving (never 409 for them); re-add remaining manual lines; then refresh. Derived row ids stay stable across updates (assert in test). `update_template=true` keeps existing behavior for manual categories; entries for deriving categories are skipped there too. `_budget_to_out` passes `source` through.

- [ ] TDD: read materializes derived lines; update preserves derived rows and their ids; payload entry for deriving category ignored; manual lines still replaceable; template-created budget skips deriving categories; source in response. Implement; suite; commit `feat(budget): lazy derived-line refresh in budget endpoints`.

### Task 3: Sync source field

**Files:** `backend/app/sync_schemas.py` (`ExportBudgetLine` gains `source: str = "manual"`); `backend/app/services/sync_export.py` (write it); `backend/app/services/sync_import.py` (set on create; existing-line conflict behavior unchanged). Tests: extend the sync roundtrip file.

**Contract:** Roundtrip preserves source; legacy files (no field) import as manual; importing derived lines into a device where the category does not derive leaves them until that device's refresh logic decides (no special-casing in import).

- [ ] TDD; implement; suite; commit `feat(budget): sync budget-line source`.

### Task 4: Frontend: derived rows + coverage nudge

**Files:** `frontend/src/lib/api.ts` (BudgetLine type gains `source`); `frontend/src/routes/budget/+page.svelte`; `frontend/src/routes/recurring/+page.svelte`.

**Contract (spec "UI" + "Coverage nudge"):** Budget page: rows with `source != "manual"` render the amount as plain text (no input), with a badge "from recurring" (links to /recurring) or "from allocation" (links to /cashflow), tooltip "Edit the recurring payment / allocation bucket to change this"; all summary/footer math untouched; the add-line inputs reject a category that already has a derived line in the current budget, showing "This category is managed by recurring payments / allocation buckets; edit those instead." client-side. Recurring page: confirmed payments with `category_id == null` get an amber "no category" badge and an inline CategoryInput (PATCH category_id, reuse existing update binding); a banner above the confirmed list shows "N recurring payments have no category yet, so the budget cannot derive them." only when N > 0. Match each page's existing visual language; 44px tap targets on mobile for the new inputs.

- [ ] Implement; `rtk proxy npm run check` 0/0; commit `feat(frontend): derived budget rows and recurring category nudge`.

### Task 5: Final verification

- [ ] Full backend suite; svelte-check; vitest (only the 7 known failures); `npm run build`. Local only; report outputs.
