# Budget Highlights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** A deterministic rule engine that turns any budget period into a Highlights panel (summary header + severity cards), encoding the manual review method; no AI, fixed templates, fully unit-tested.

**Architecture:** New pure service `budget_highlights.py` consuming the existing budget-vs-actual computation plus period transactions; one new endpoint on the budgets router; one new frontend component rendered at the top of the Actuals tab.

**Tech Stack:** FastAPI + SQLAlchemy + pytest; SvelteKit + Svelte 5. No migrations (no new persisted state).

**Spec:** docs/superpowers/specs/2026-09-23-budget-highlights-design.md is binding; it overrides this plan on conflict.

## Global Constraints

- No em-dashes. Conventional commits, no attribution footer. TDD with RED evidence.
- Backend baseline 399 tests stays green; svelte-check 0/0; the 7 known uncategorized.test.ts failures untouched. `rtk proxy` for pytest/vitest.
- Period date convention half-open `[start_date, end_date)` in every new query.
- All thresholds as module constants exactly as the spec names them.
- Local only until the controller merges; push/deploy handled by the controller afterwards.

---

### Task 1: Refactor budget-vs-actual into a reusable computation

**Files:** `backend/app/routers/dashboard.py` (extract), new `backend/app/services/budget_actuals.py`; tests: existing suites stay green (pure refactor, no behavior change; `test_budget_api.py` and `test_dashboard_insights.py` are the regression net).

**Contract:** The body of the budget-vs-actual endpoint (actuals per category incl. the savings-contribution override, budgeted/source maps, income/expense line assembly, totals) moves into `compute_budget_actuals(db, budget) -> BudgetActualsResult` (a dataclass mirroring today's response content). The endpoint becomes a thin mapper; response bytes are unchanged (assert by keeping all existing tests untouched and green). This gives the highlights engine one blessed input instead of re-deriving actuals.

**Produces:** `compute_budget_actuals` with fields the next task consumes: per-line category_id/category_type/is_fixed/source/budgeted/actual, plus totals and the period dates.

- [ ] Refactor; full suite green with zero test edits; commit `refactor(budget): extract budget-vs-actual computation into a service`.

### Task 2: Highlights engine (spec "Rule catalog", binding)

**Files:** new `backend/app/services/budget_highlights.py`; tests: new `backend/tests/test_budget_highlights.py`.

**Interfaces (produces):** `compute_highlights(db, budget, today: date | None = None) -> HighlightsResult` where HighlightsResult carries `closed: bool`, `summary` (raw_net, incidental_total, incidental_by_label list, unlabeled_incidental, structural_net, flexible_within_plan, flexible_total, pots_executed, pots_planned) and `highlights: list[Highlight(rule, severity, title, detail, category_id, amount)]`.

**Contract:** Implement R1-R9 exactly per spec (R10 deferred: the engine accepts a `prior_overruns: set[int]` argument that v1 callers pass empty and no rule reads yet). Honor: closed-vs-open catalogs; subtree aggregation for R4/R5/R9 (descendant actuals fold into the nearest ancestor plan line; descendants with their own line judged separately); one-off detector over the same descendant set at ONE_OFF_FRACTION of aggregated actual; R5 emits at most one card; R6's five branches with the aggregate all-funded good card; R8's tie-breaks (amount, datum, id); global ordering (catalog order, |amount| desc, category_id asc); per-rule error isolation (log + skip). All constants module-level with the spec's names and values. All queries half-open on dates.

- [ ] TDD (RED first) covering the spec's Testing list: ghost only when closed; overrun boundary (exactly at threshold no, one cent over yes); subtree aggregation (plan on parent, spend on children; child with own line excluded); one-off at the 50% boundary; R5 single-card cap; R6 all branches incl. withdrawal transaction listing and the aggregate good card; R7 both directions at the 2% boundary; R8 ordering + tie-break; R9 counts consistent with fired R4; full-list ordering; open-period reduced catalog; R1 normalization with labeled incidental spend, incidental income, and unlabeled incidental; rounding.
- [ ] Implement; full suite; commit `feat(budget): deterministic highlights engine`.

### Task 3: Endpoint

**Files:** `backend/app/routers/budget.py` (GET `/api/budgets/{id}/highlights`), `backend/app/schemas.py` (HighlightOut, HighlightsSummaryOut, BudgetHighlightsOut mirroring the spec's JSON). Tests: extend `backend/tests/test_budget_api.py`.

**Contract:** 404 on unknown budget; otherwise maps `compute_highlights(db, budget)` 1:1; refreshes derived lines first for open budgets exactly like `get_budget` does (so highlights see current plans); `closed` computed with `date.today()`.

- [ ] TDD (shape, 404, closed flag for a past and a current budget); implement; suite; commit `feat(budget): highlights endpoint`.

### Task 4: Frontend Highlights panel

**Files:** `frontend/src/lib/api.ts` (types + `getBudgetHighlights(budgetId)`); new `frontend/src/lib/components/BudgetHighlights.svelte`; `frontend/src/routes/budget/+page.svelte` (render at the top of the Actuals tab, fetch alongside bva, pass the period's inclusive spending-link suffix).

**Contract (spec "UI"):** Header row: structural net bold, raw net + incidental breakdown as muted caption ("raw net EUR -1,580 incl. Vakantie EUR 633, unlabeled EUR 800"), scorecard counts, "(period in progress)" suffix when open. Cards in returned order with left-border severity accents reusing the existing green/amber palette tokens; a card with category_id wraps in a link to `/spending/category/{id}` with the same inclusive date suffix the row links use; empty list renders "Nothing notable yet."; failures show ErrorBanner without blocking the tables below (independent fetch, own error state). Mobile: full-width stacked cards, whole card tappable.

- [ ] Implement; `rtk proxy npm run check` 0/0; commit `feat(frontend): budget highlights panel`.

### Task 5: Final verification

- [ ] Full backend suite; svelte-check; vitest (only the 7 known failures); `npm run build`. Report outputs. Local only.
