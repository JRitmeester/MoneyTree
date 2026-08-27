# Categories & Offsets Implementation Plan (UX review wave 2)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Checkbox steps.

**Goal:** Category merge, per-parent name uniqueness with path-keyed sync, root-add/re-parent UI, offsets that genuinely net out in analytics, bulk-action undo, and the extractErrorDetail cleanup.

**Architecture:** Category identity in sync moves from bare name to full path ("Vrije Tijd > Overig"). Merge is a backend operation that re-points all references. Offset netting happens inside the existing `_iter_expense_items`/summary computations so every analytics surface benefits at once.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + pytest; SvelteKit + Svelte 5 + vitest.

**Spec:** UX review findings agreed by the user; sync path-key ruling below is the authority for conflicts.

## Global Constraints

- No em-dashes anywhere. Conventional commits, no attribution footer. TDD with RED evidence.
- Backend suite (156+) and svelte-check (0/0) stay green; the 7 pre-existing uncategorized.test.ts failures stay untouched.
- Sync compatibility: export format_version bumps to 3 in Task 2; v1/v2 files (bare-name category keys) must keep importing correctly.
- Briefs are contracts; implementers read code first.

---

### Task 1: Category merge (backend + UI)

**Files:** `backend/app/routers/categories.py`, `backend/app/schemas.py`, `frontend/src/routes/categories/+page.svelte`, `frontend/src/lib/api.ts`. Test: extend `backend/tests/test_categories.py`.

**Contract:** `POST /api/categories/{source_id}/merge-into/{target_id}`: re-points transactions, line items, budget lines (when the target already has a line in the same budget, sum the amounts instead of duplicating; respect the unique budget+category constraint), budget templates (same summing rule), category mappings, and incidental-label-free; children of source are re-parented to target; source is deleted; source == target or target being a descendant of source is a 400. Records a sync event analogous to rename/delete so other devices converge (follow the existing EVENT_CATEGORY_* pattern; a merge event = re-point by name then delete). Returns counts of re-pointed rows. UI: a "Merge into..." action per category row opening a CategoryInput picker + confirm dialog stating the counts from a dry-run (add `?dry_run=true` support returning counts without mutating).

- [ ] TDD: dry-run counts; full merge re-points everything incl. budget-line summing; descendant-target rejected; sync event recorded. Then implement; suite; check; commit `feat(categories): merge categories`.

### Task 2: Per-parent category names + path-keyed sync

**Files:** `backend/app/models.py` (+ alembic migration), `backend/app/routers/categories.py`, `backend/app/services/sync_export.py`, `sync_import.py`, `sync_schemas.py`. Tests: `test_categories.py` + sync test files.

**Contract:** Replace the global unique constraint on `categories.name` with UniqueConstraint(parent_id, name) (migration must handle SQLite table-rebuild semantics; verify with alembic upgrade on a copy). Create/rename/merge validate uniqueness among siblings (friendly 409). Sync moves to path keys: export format_version 3 writes `path` ("Parent > Child > Leaf", using the existing " > " separator convention from _full_category_name) for categories and every category reference (budget lines, templates, mappings, transactions, line items). Import: v3 resolves by path (creating missing ancestors); v1/v2 files resolve by bare name exactly as today (unambiguous pre-change data). Rename/delete sync events carry paths in v3.

- [ ] TDD first (sibling duplicate allowed under different parents; same-parent duplicate 409; v3 roundtrip with two "Overig" categories under different parents; v2 legacy import still works). Implement. Full suite. Commit `feat(categories): per-parent names with path-keyed sync (format v3)`.

### Task 3: Root-add and re-parent UI

**Files:** `frontend/src/routes/categories/+page.svelte` (+ api.ts if needed). Tests: svelte-check gate; backend already supports parent_id PATCH.

**Contract:** An "Add category" button at the top of the page (root-level create, with type selector); a "Move to..." action per row opening a CategoryInput picker (allow "no parent" = root; reject moving under own descendant client-side with a clear message; backend already validates via 409s where applicable, surface them). Keep the page's existing visual language.

- [ ] Implement with `npm run check` clean; commit `feat(categories): root add and re-parent from the UI`.

### Task 4: Offsets net out in analytics

**Files:** `backend/app/routers/dashboard.py`, possibly a helper in `backend/app/services/`, `frontend/src/routes/transactions/+page.svelte` (badge). Tests: extend `backend/tests/test_dashboard_insights.py`.

**Contract:** Everywhere analytics iterate transactions (summary, monthly-trend, savings-capacity) and expense items (`_iter_expense_items` for by-category/category-detail/budget-vs-actual): an income transaction that is linked as an offset is EXCLUDED from income, and the linked expense counts at `abs(bedrag) - offset_total` (floor 0). Receipt-split expenses already handle this via the remaining line item: do NOT double-subtract there (the offset reduces only the no-receipt path amount; verify against services/remaining.py behavior and document the rule in a comment). Transactions list shows an "offset" badge on both sides (income linked as offset; expense with offsets), with the transaction detail page unchanged. TransactionOut gains `offset_total: float = 0.0` and `is_offset_income: bool = False` (computed in the list endpoint).

- [ ] TDD: summary with a 100 expense + 30 linked income shows expenses 70 and income excluding the 30; category spending shows 70; receipt-split case not double-subtracted; monthly trend consistent. Implement. Suite. check. Commit `feat(offsets): net linked offsets out of all analytics`.

### Task 5: Bulk-action undo + error-helper cleanup

**Files:** `frontend/src/lib/errors.ts` (new; move extractErrorDetail, update the two duplicating pages), `frontend/src/routes/transactions/+page.svelte`, `frontend/src/routes/uncategorized/+page.svelte`. Test: `frontend/src/lib/transactionFlags.test.ts` pattern for any pure helper.

**Contract:** After a bulk action on the transactions page (flags) or uncategorized page (categorize), show a toast/bar "Applied to N transactions · Undo" for 10 seconds. Undo restores the previous state captured client-side before the action (for flags: previous flag/label values per id via bulk-flags and per-id PATCH where values differ; for categorization: previous category_id per id via categorize-selected/PATCH). Keep it simple and client-side; no backend changes. If the user navigates away, the undo option is simply gone.

- [ ] Implement with a small pure helper (computeUndoPayloads) unit-tested; `npm run check` clean; commit `feat(frontend): undo for bulk actions`.

### Task 6: Final verification

- [ ] Full backend suite; svelte-check; vitest (only the 7 known failures); `npm run build`. Report outputs. Local only; no deploy, no push.
