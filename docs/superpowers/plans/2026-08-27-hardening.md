# Hardening Implementation Plan (UX review wave 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fix the three data-safety bugs from the UX audit, make the sync export cover everything user-created, and close the small UX gaps (import feedback, mapping save, dashboard cards, amount search, staleness).

**Architecture:** Backend-first per task with TDD; each task carries its own frontend change where one exists. No new subsystems; all changes extend existing routers/pages.

**Tech Stack:** FastAPI + SQLAlchemy + pytest; SvelteKit + Svelte 5 + vitest.

**Spec:** The UX review findings in this conversation, agreed by the user, plus docs/superpowers/specs/2026-08-27-financial-insights-design.md for flag semantics.

## Global Constraints

- No em-dashes anywhere (code, comments, commit messages, UI copy).
- Conventional commits, no attribution footer.
- TDD: failing test first for every behavior change; RED evidence in reports.
- Backend tests: `python -m pytest tests/ -q` from backend/ (121+ tests must stay green). Frontend: `npm run check` 0 errors 0 warnings; `npx vitest run` (7 pre-existing failures in uncategorized.test.ts are known and out of scope).
- Implementers read the current code before editing; the briefs give contracts, not verbatim files.
- Existing API responses may gain fields but must not remove or rename existing ones (device-sync compatibility), except where a task says otherwise.

---

### Task 1: Category PATCH must not reset flags

**Files:** Modify `backend/app/routers/categories.py`, `backend/app/schemas.py`, `frontend/src/routes/categories/+page.svelte`. Test `backend/tests/test_categories.py` (new file).

**Contract:** Add `CategoryUpdate` schema with ALL fields optional (`name`, `parent_id`, `category_type`, `is_fixed`). `PATCH /api/categories/{id}` switches to it and applies only fields present in the request (`model_dump(exclude_unset=True)`), keeping the rename sync-event behavior. The create path keeps `CategoryCreate` unchanged. Frontend: `saveRename` sends only `{name}`, `handleToggleType` only `{category_type}`.

- [ ] Step 1: Failing tests: rename-only PATCH preserves `is_fixed=True` and `category_type="income"`; type-toggle-only PATCH preserves `is_fixed`; PATCH with explicit `is_fixed` still works. Run, expect FAIL (current behavior resets to defaults).
- [ ] Step 2: Implement schema + router change; update frontend calls (check `updateCategory` signature in api.ts, loosen its payload type to Partial if needed).
- [ ] Step 3: Full backend suite + `npm run check`. Commit `fix(categories): PATCH applies only provided fields, stops resetting is_fixed`.

### Task 2: Safe category delete

**Files:** Modify `backend/app/routers/categories.py`, `frontend/src/routes/categories/+page.svelte`. Test: extend `backend/tests/test_categories.py`.

**Contract:** `DELETE /api/categories/{id}` checks references before deleting: transactions (`category_id`), line items, budget lines, budget templates, category mappings. If any exist, return 409 with detail like `"Category is in use: 12 transactions, 2 budget lines. Reassign them first."` (list only non-zero kinds). Children check stays. Frontend shows the detail text in the page's existing error area (verify it does not swallow it).

- [ ] Step 1: Failing tests: delete of category referenced by a transaction returns 409 with a count in the message; delete of unreferenced leaf category still works; category with children still 409.
- [ ] Step 2: Implement counts + message. Keep it one query per table, no ORM cascade changes.
- [ ] Step 3: Suite green, check clean. Commit `fix(categories): block deleting categories that are still referenced`.

### Task 3: Friendly CSV import errors + categorization feedback

**Files:** Modify `backend/app/services/csv_parser.py`, `backend/app/routers/transactions.py`, `backend/app/schemas.py` (ImportResult), `frontend/src/routes/import/+page.svelte`. Test: `backend/tests/test_import.py` (new file).

**Contract:**
- Parser raises a dedicated `CsvFormatError(ValueError)` with a human message naming the row number and problem (wrong column count, bad date, bad amount). Router catches it and returns 400 `{"detail": "<message>"}`. Any other exception during parse also becomes a 400 "This does not look like an ASN Bank CSV export" rather than a 500.
- `ImportResult` gains `categorized: int` and `uncategorized: int` (counts over the newly imported rows only, based on whether the mapping assigned a category_id).
- Import page: show both counts after import; when `uncategorized > 0`, render a prominent link "Categorize N transactions →" to `/uncategorized`, alongside the existing transactions link.

- [ ] Step 1: Failing tests: import of a file with a bad amount in row 3 returns 400 mentioning row 3; import of garbage bytes returns 400 not 500; successful import returns correct categorized/uncategorized counts (seed one CategoryMapping so one row auto-categorizes).
- [ ] Step 2: Implement; reuse the existing test CSV fixture pattern from tests/test_transfers.py (header row required).
- [ ] Step 3: Suite green, check clean. Commit `feat(import): friendly CSV errors and categorization counts`.

### Task 4: Sync export/import covers flags, labels, own accounts

**Files:** Modify `backend/app/sync_schemas.py`, `backend/app/services/sync_export.py`, `backend/app/services/sync_import.py`, bump the export format version if one exists. Tests: extend `backend/tests/test_sync_export.py` and `backend/tests/test_sync_import_commit.py` (follow their existing patterns closely).

**Contract:**
- `ExportTransaction` gains `is_internal_transfer: bool = False`, `is_internal_transfer_manual: bool = False`, `is_incidental: bool = False`, `incidental_label: str | None = None` (label BY NAME, consistent with the export's name-as-key convention).
- New top-level export lists: `incidental_labels: list[str]` (names) and `own_accounts: list[ExportOwnAccount]` (iban, name, account_type, starting_balance, starting_balance_date).
- Import: creates missing labels by name; creates missing own accounts by IBAN (existing IBAN: keep destination row, count as skipped); on NEW transactions applies all four fields (resolving label name to id); on EXISTING transactions, flags are applied only when the destination row has all-default flag values (never overwrite a destination's non-default curation; count these as soft conflicts in the preview like the existing category conflict pattern).
- Old export files without the new fields must import cleanly (defaults). Preview counts must mention new entity types (follow how categories are counted).

- [ ] Step 1: Failing tests: roundtrip export→import into empty DB preserves all four transaction fields, labels, own accounts; import of a legacy-format file (fields absent) still works; existing-transaction flag conflict counted not overwritten.
- [ ] Step 2: Implement export, then import, then preview counts.
- [ ] Step 3: Full suite green (the 11 sync test files are the regression net here, run them all). Commit `feat(sync): include incidental flags, labels, and own accounts in export/import`.

### Task 5: Sync includes standalone receipts

**Files:** Same sync files as Task 4. Tests: extend `backend/tests/test_sync_receipts.py`.

**Contract:** Receipts with no linked transaction are exported too (`transaction_import_hash: null`). On import, a standalone receipt is created unless an existing receipt matches on (date, total_amount, merchant_name, ocr_raw_text) exactly, in which case it is skipped as a duplicate. Update the ExportReceipt docstring that currently says they are excluded.

- [ ] Step 1: Failing test: standalone receipt with image roundtrips; importing the same file twice does not duplicate it.
- [ ] Step 2: Implement. Step 3: suite green. Commit `feat(sync): export standalone receipts`.

### Task 6: Uncategorized page: save-mapping flow + empty-state CTA

**Files:** Modify `frontend/src/routes/uncategorized/+page.svelte` (and api.ts only if a binding is missing; `bulkCategorize` already exists). Update `frontend/src/routes/uncategorized/uncategorized.test.ts` ONLY by adding new tests; do not attempt to fix the 7 pre-existing failures.

**Contract:**
- Each bank-category group header shows a "mapped" indicator when `has_mapping` is true.
- When the user selects an entire group (group checkbox) and applies a category, offer a checkbox "Also map bank category 'X' to this category for future imports" (default checked); when set, call the existing `bulkCategorize(bankCategory, categoryId, saveMapping)` endpoint instead of categorize-selected; partial selections keep using categorize-selected with no mapping offer.
- Empty state gains a link back to the dashboard.

- [ ] Step 1: Add component tests for the new behavior following the file's existing mock pattern (group fully selected shows mapping checkbox; applying calls the bulk endpoint with save_mapping).
- [ ] Step 2: Implement. Step 3: `npm run check` clean; new tests pass; the 7 known failures remain the only failures. Commit `feat(uncategorized): save bank-category mappings from the page`.

### Task 7: Dashboard: savings-rate card, transfer detail, data-through staleness

**Files:** Modify `backend/app/routers/dashboard.py` + `backend/app/schemas.py` (DashboardSummary gains `data_through: date | None`, the max transaction datum over ALL data, ignoring the range filter), `frontend/src/routes/+page.svelte`. Tests: extend `backend/tests/test_dashboard_insights.py`.

**Contract:**
- DashboardSummary gains `data_through`. Frontend header shows "Data through 27 Aug 2026" next to the date filter; when older than 7 days vs today, style it amber with title "Import your latest bank export".
- New summary card "Saved" showing `net / total_income` as a percentage when `total_income > 0` (omit card otherwise); shown alongside Net (never replaces the budget-pace card).
- The "To savings" card's detail line additionally shows `in €X / out €Y` from transfers_in/transfers_out.

- [ ] Step 1: Failing backend test for data_through (max datum regardless of date filter; null on empty DB). Step 2: implement backend then frontend. Step 3: suite + check green. Commit `feat(dashboard): savings rate, transfer detail, data-through indicator`.

### Task 8: Amount search on transactions

**Files:** Modify `backend/app/routers/transactions.py`, `frontend/src/routes/transactions/+page.svelte` (placeholder text only: "Search description, merchant, or amount..."). Tests: extend `backend/tests/test_transfers.py` or a new test file.

**Contract:** In `list_transactions`, when `search` parses as a number using Dutch or dot notation (`46`, `46,95`, `46.95`, optional leading minus or euro sign), the filter becomes: text match (existing ilike) OR `abs(bedrag)` within 0.005 of the parsed value. Non-numeric searches behave exactly as before.

- [ ] Step 1: Failing tests: search "46,95" finds a -46.95 transaction whose text contains no "46"; search "banana" still text-matches; search "46.95" also works. Step 2: implement a small `_parse_amount(search)` helper. Step 3: suite green, check clean. Commit `feat(transactions): search by amount`.

### Task 9: Final verification

- [ ] Full backend suite; `npm run check`; `npx vitest run` (only the 7 known failures). Build the frontend (`npm run build`) to prove the bundle compiles. Report actual outputs. No NAS deploy in this plan.
