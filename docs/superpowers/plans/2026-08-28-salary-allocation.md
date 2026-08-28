# Salary Allocation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement the salary allocation plan: configurable buckets (fixed euro or percent-of-remainder) dividing each received salary after the recurring-bills pot, shown as a payday checklist on /cashflow.

**Architecture:** New `allocation_buckets` table + CRUD router; a pure `salary_allocator.py` service consuming an anchored variant of the existing transfer advisor; one read endpoint on the cashflow router; sync section following the incidental_labels/own_accounts pattern; a new frontend card component on the cashflow page.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + pytest; SvelteKit + Svelte 5.

**Spec:** docs/superpowers/specs/2026-08-28-salary-allocation-design.md is the binding authority for every task. Its details override this plan on conflict.

## Global Constraints

- No em-dashes anywhere. Conventional commits, no attribution footer. TDD with RED evidence.
- Backend baseline 325 tests stays green; svelte-check 0/0; the 7 known uncategorized.test.ts failures stay untouched.
- `rtk proxy` prefix for pytest/vitest output accuracy.
- Alembic head is currently o5p6q7r8s9t0; the new migration chains from it. Single head after.
- All new endpoints under the existing `require_auth` dependency.
- Local only: no push, no NAS deploy (controller handles that after final verification).

---

### Task 1: Data model, migration, bucket CRUD, lifecycle integration (spec: "Data model", "Validation rules", "Bucket CRUD")

**Files:** `backend/app/models.py` (AllocationBucket) + new alembic migration; `backend/app/schemas.py` (AllocationBucketOut, AllocationBucketCreate, AllocationBucketUpdate, AllocationBucketOrderUpdate); new `backend/app/routers/allocation_buckets.py`; `backend/app/main.py` (register router); `backend/app/routers/settings.py` (delete-everything wipes allocation_buckets); `backend/app/routers/categories.py` (delete + merge). Tests: new `backend/tests/test_allocation_api.py`.

**Contract:** Table exactly per spec (name unique, rule_type fixed/percent, value, position, nullable category_id, is_active). CRUD per spec: GET all ordered by position; POST appends at max+1; PATCH partial via `model_fields_set`/`exclude_unset` with explicit-null clearing category_id (follow the bulk-flags label pattern); DELETE hard-deletes and re-compacts positions 0..n-1; PUT /api/allocation-buckets/order takes `{"ids": [...]}`, 400 unless the id set exactly matches all existing buckets, rewrites positions server-side. Validation 409s: duplicate name (case-sensitive, trimmed), percent cap (sum of value over ACTIVE percent buckets > 100 after the write, including activating a paused bucket); 422 via pydantic for rule_type/value ranges (fixed value > 0, percent 0 < value <= 100). category_id must reference an existing category (404 otherwise). Lifecycle: `delete_everything` adds `db.execute(delete(AllocationBucket))` in FK order; category DELETE clears `category_id` on linked buckets BEFORE the reference check and does NOT count buckets as blocking references (spec: deleting a category never deletes or blocks on a bucket); category merge re-points `allocation_buckets.category_id` from source to target and includes the count in CategoryMergeCounts (extend dry_run too).

**Produces (later tasks rely on):** model `AllocationBucket` with exactly the spec's columns; router mounted at `/api/allocation-buckets`.

- [ ] TDD (CRUD happy paths; duplicate-name 409; percent-cap 409 on create, update, and re-activate; reorder + mismatch 400; delete re-compaction; category delete clears link; merge re-points; delete-everything wipes). Implement. Full suite. Commit `feat(allocation): bucket data model and CRUD API`.

### Task 2: Anchored advisor variant + salary allocator service (spec: "Allocation calculation", binding)

**Files:** `backend/app/services/cashflow_advisor.py` (add keyword-only `anchor_payday: date | None = None` to `compute_advice`); new `backend/app/services/salary_allocator.py`; tests: new `backend/tests/test_salary_allocator.py` + extend `backend/tests/test_cashflow_advisor.py` for the anchored mode.

**Contract:** Anchored advice: when `anchor_payday` is given, the sweep window is `[anchor_payday, _next_payday_after(salary, anchor_payday))` with identical shifting/clustering/keep-in-checking/buffer logic; the stale-payday roll-forward (and its warning) is skipped; forward-looking behavior is byte-identical when `anchor_payday` is None (existing 17 advisor tests must pass unchanged). Allocator: `compute_allocation(db, buffer_pct, today=None)` returning a frozen dataclass `SalaryAllocation` with fields matching the spec's response JSON (salary_confirmed, message, payday, basis "actual"/"expected", salary_amount, bills_pot, kept_in_checking, lines: list[AllocationLine(bucket_id, name, rule_type, value, amount, category_id, category_name, shortfall)], free_to_spend, warnings). Anchor selection per spec: latest salary occurrence date + actual amount when occurrences exist (basis "actual"); else next expected shifted payday + expected_amount (basis "expected"); no confirmed salary mirrors the advice empty state. Stale-anchor warning per spec when the anchored period already ended. Waterfall exactly per spec: remaining = salary - bills_pot - kept_in_checking, clamp-all-to-zero warning when negative; fixed buckets in position order get min(value, remaining) with ONE shortfall warning naming the first bucket receiving less than configured and per-line shortfall flags on fixed lines only; percent buckets share the post-fixed base, `floor_to_cent` each; free_to_spend = salary - bills_pot - kept_in_checking - sum(amounts), absorbing rounding so all rows sum exactly to salary; nothing negative; inactive buckets omitted entirely. category_name is the full " > " path (use the existing category_paths helper).

**Produces:** `compute_allocation` signature and `SalaryAllocation`/`AllocationLine` dataclasses above; `compute_advice(..., anchor_payday=...)`.

- [ ] TDD (fixed+percent mix rows sum exactly to salary; percent flooring leftover lands in free_to_spend; shortfall order + single warning + flags; salary below bills pot clamps with warning; inactive skipped; actual vs expected basis; stale-anchor warning; anchored window boundaries; forward-looking regression). Implement. Full suite. Commit `feat(allocation): anchored advisor and salary allocator service`.

### Task 3: Allocation read endpoint (spec: "GET /api/cashflow/allocation")

**Files:** `backend/app/routers/cashflow.py`; `backend/app/schemas.py` (SalaryAllocationOut, SalaryAllocationLineOut mirroring the Task 2 dataclasses). Tests: extend `backend/tests/test_allocation_api.py`.

**Contract:** `GET /api/cashflow/allocation` maps `compute_allocation(db, get_buffer_pct(db))` to the response model 1:1. Unconfirmed-salary state returns salary_confirmed=false + message with empty/null remaining fields, matching the advice endpoint's shape. Zero/absent buffer setting uses DEFAULT_BUFFER_PCT (already the `get_buffer_pct` behavior; do not duplicate logic).

- [ ] TDD (confirmed path with buckets end-to-end through the API; unconfirmed shape; empty-buckets case returns lines=[] with pot and free_to_spend still computed). Implement. Suite. Commit `feat(allocation): cashflow allocation endpoint`.

### Task 4: Sync export/import (spec: "Sync", binding, incl. position normalization)

**Files:** `backend/app/sync_schemas.py` (ExportAllocationBucket {name, rule_type, value, position, is_active, category_path: Optional[str]}; ExportFile gains `allocation_buckets: list[ExportAllocationBucket] = Field(default_factory=list)`); `backend/app/services/sync_export.py`; `backend/app/services/sync_import.py`. Tests: extend the existing sync test files (find them via `grep -rl sync_export backend/tests`).

**Contract:** Export writes all buckets (active and paused) with category_path as the " > " full path or null. Import (any format_version, since the field defaults to empty): upsert by exact name; existing bucket updated (rule_type, value, is_active, category link), missing created; local-only buckets untouched; category_path resolved exactly like other v3 category references (creating missing ancestors), null clears the link, and a path that only resolves ambiguously by bare name in v1/v2 files follows whatever convention those importers use for other category refs. Position normalization per spec: imported positions are relative order only; after upsert re-sort (file order first, then local-only buckets in existing relative order) and rewrite 0..n-1. Import preview/counts surfaces follow whatever the labels/own-accounts sections already do (mirror, do not invent).

- [ ] TDD (roundtrip export→import into empty db; upsert-by-name updates; local-only preserved + normalization produces 0..n-1 unique positions; category_path creates ancestors; legacy file without section unaffected). Implement. Full suite. Commit `feat(allocation): sync export/import for allocation buckets`.

### Task 5: Frontend allocation card (spec: "UI", binding)

**Files:** `frontend/src/lib/api.ts` (AllocationBucket, SalaryAllocation types + getSalaryAllocation, listAllocationBuckets, createAllocationBucket, updateAllocationBucket, deleteAllocationBucket, reorderAllocationBuckets); new `frontend/src/lib/components/SalaryAllocationCard.svelte` (keep the cashflow page from growing past the file-size guideline); `frontend/src/routes/cashflow/+page.svelte` (mount the card below the advice card, pass nothing: the card fetches its own data on mount and after every edit).

**Contract:** View mode per spec: title "Salary allocation"; subtitle naming payday + basis ("Salary received Fri 23 Aug" / "Expected salary, not yet received"); waterfall rows in order: bills pot (muted, captioned "covers bills until next payday", NEVER annotated as equal to the advice card figure), kept-in-checking (only when nonzero, muted), one row per active bucket (name, amount, muted rule caption "fixed" or "N% of remainder", linked category path when set, amber note when shortfall), bold "Free to spend". Warnings reuse the page's existing `.warning-box` styling (extract to a shared component or copy the classes; do not restyle). Edit mode via "Edit buckets" toggle: inline rows with name input, rule-type select, value input with EUR/% adornment, CategoryInput for the goal link (clearable), pause/resume, delete with confirm, up/down reorder buttons calling the reorder endpoint with the full id list; auto-save on blur/Enter like the budget page; errors via extractErrorDetail shown inline per row (409s) or in the page ErrorBanner (fetch failures). Empty states: no buckets -> explanation + "Add your first bucket" opening edit mode; no confirmed salary -> render nothing (the advice card already shows the confirm-salary state; spec forbids duplicating it). Mobile: rows wrap cleanly at 400px; tap targets 44px for the reorder/pause/delete buttons.

- [ ] Implement; `rtk proxy npm run check` 0/0; commit `feat(frontend): salary allocation card on cashflow page`.

### Task 6: Final verification

- [ ] Full backend suite; svelte-check; vitest (only the 7 known failures); `npm run build`. Report outputs. Local only; no deploy, no push.
