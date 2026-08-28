# Derived Budget Lines — Design

Date: 2026-08-28
Status: approved direction (Option A: derivation), spec for review

## Purpose

Two facts currently live in two places each, drifting independently:

1. Fixed bill amounts: hand-entered budget lines vs confirmed recurring
   payments (which self-update as amounts drift).
2. Savings contributions: hand-entered budget lines vs allocation buckets.

This design makes the recurring payments and allocation buckets the single
owners of those facts. The budget's Fixed and Savings sections become
system-maintained wherever authoritative data exists, and stay manual
where it does not. Guiding principle (user, 2026-08-28): Cash flow is
where money MOVES; Budget is where spending is TRACKED per month. The
budget keeps tracking; it just stops asking the user to re-type numbers
the system already knows.

## Core mechanism: materialized derived lines

`budget_lines` gains a column `source: str` (default `"manual"`, values
`"manual" | "recurring" | "allocation"`). Derived lines are real stored
rows, so every existing consumer (savings running balances, budget-vs-
actual, sync, exports) keeps working unchanged. The system refreshes them;
the user cannot edit them.

### Refresh rules

- Refresh happens lazily on budget read (`GET /api/budget/{id}` and the
  list endpoint for the periods it returns), inside the same transaction.
- Only budgets with `end_date >= today` are refreshed. Past periods are
  frozen history: whatever lines they hold (manual or previously derived)
  stay untouched, so running balances and past reports never rewrite
  themselves.
- Refresh is idempotent: compute the derived target state, upsert rows
  (unique budget+category constraint respected), delete stale derived rows
  (source != "manual") whose category no longer derives anything, and
  leave manual rows alone.
- A manual line for a category that NOW derives is replaced by the derived
  line (its amount is superseded; the row's source flips and amount is
  overwritten). This is the one-way adoption path.

### Derivation: Fixed section (source = "recurring")

For each confirmed, non-income recurring payment WITH a `category_id`:
project its occurrences into the budget period `[start_date, end_date)`
using the cashflow advisor's `occurrences_in_range(payment, start, end,
shift_weekend=True)`. Group by category; the derived amount per category
is the sum of `abs(expected_amount)` over all projected occurrences of all
payments in that category. Consequences, intended:

- A four-weekly bill occurring twice in one period counts twice.
- A yearly premium appears only in the period it actually lands, at full
  amount (no amortizing; the Insights page already shows amortized views).
- When FBTO raises the premium, the next refresh updates the budget.

Payments without a category derive nothing (see "Coverage nudge").
Direction/typing: the derived amount is stored positive, matching existing
budget-line conventions.

### Derivation: Savings section (source = "allocation")

For each ACTIVE allocation bucket WITH a `category_id`: for each salary
occurrence date in the period (actual occurrences; if none and the period
is current/future, the projected shifted payday(s) in the period), compute
that payday's allocation waterfall (the existing `salary_allocator` logic
anchored at that payday) and take this bucket's computed euro amount.
The salary amount per payday is the actual occurrence amount when an
occurrence exists, else the salary's `expected_amount` (projected
paydays). Derived amount per category = sum over paydays in the period.
So:

- Fixed buckets contribute `value` per payday.
- Percent buckets contribute the actual computed euros for that period's
  salary, so vakantiegeld months show a bigger planned contribution.
- A period with no payday (short/odd periods) derives 0 and therefore no
  line.

Unlinked buckets (no category) never touch the budget. If a category
somehow has both recurring payments and a bucket, savings-type categories
prefer "allocation", expense-type prefer "recurring" (one source per
line, deterministic).

## API and validation

- `BudgetLineOut` gains `source: str`. No new endpoints.
- The budget update endpoint receives the full line set from the page's
  auto-save. It must NOT 409 just because derived lines ride along:
  entries for categories that currently derive are silently ignored
  (the refresh recomputes them authoritatively in the same request).
  This keeps the existing frontend save flow working unmodified.
- The bulk update's delete-missing-lines behavior applies to MANUAL rows
  only. Derived rows are never deleted by the update endpoint (only by
  the refresh when their category stops deriving), so their row ids stay
  stable across auto-saves instead of churning delete+recreate.
- Explicitly creating a NEW line for a category that currently derives
  (a line for a deriving category that was not in the budget before the
  request) returns 409: "This category is managed by recurring payments
  / allocation buckets; edit those instead." The UI also blocks it
  client-side in the add-line typeahead.
- `BudgetTemplate` is untouched, but `_create_from_template` skips
  template lines whose category would derive (the refresh creates the
  derived line immediately after creation).

## Sync

`ExportBudgetLine` gains optional `source: str = "manual"`. Lines export
with their source; import preserves it (older files import as manual,
which the next refresh on the receiving device adopts if the category
derives there). No format version bump: pydantic defaults handle absent
fields, same as previous additive changes.

## UI (budget page)

- Derived rows render read-only: no amount input; a small badge "from
  recurring" / "from allocation" (tooltip: "Edit the recurring payment /
  allocation bucket to change this"). Badge links to /recurring or
  /cashflow respectively.
- Manual rows keep today's editing exactly.
- Section footers and summary math unchanged (they sum lines regardless
  of source).
- Add-line typeahead in Fixed/Savings sections rejects categories that
  currently derive, surfacing the 409 message inline.

## Deliberate exclusions and accepted limitations

- The Income section stays manual. Salary is derivable from the confirmed
  recurring income, but income is one number that rarely needs editing;
  the drift pain lives in Fixed/Savings. Income derivation is a trivial
  follow-up once this design proves itself.
- Freeze-boundary staleness: a period's derived lines are last updated by
  its last read while still open (end_date >= today). A period never
  viewed near its end keeps slightly older derived values. Accepted: the
  alternative (refreshing recently-ended periods) reopens the
  history-rewriting problem this design exists to prevent.
- Upgrade moment: the first read of the current period after this ships
  adopts existing manual Fixed/Savings lines whose categories derive,
  overwriting their amounts with the recurring/bucket truth in one
  predictable step. The badges explain where the numbers now come from.
  A test asserts the adoption happens exactly once (idempotent after).

## Coverage nudge (Recurring page)

Confirmed recurring payments without a category get a visible hint:
an amber "no category" badge on the row plus an inline CategoryInput to
set it (PATCH already supports category_id). A one-line banner above the
confirmed section counts unlinked payments: "N recurring payments have no
category yet, so the budget cannot derive them." No new endpoints.

## Error handling

- Refresh never 500s a budget read: derivation errors for one payment or
  bucket are skipped (logged server-side) and the rest still derive.
- Percent-bucket derivation with no confirmed salary derives nothing
  (no line), consistent with the allocation card's empty state.

## Migration

Alembic migration (chains from current head p6q7r8s9t0u1) adds
`budget_lines.source` with server default `"manual"`. No data backfill:
the first read of a current/future budget performs the adoption.

## Testing

- Unit tests for the refresh function: fixed derivation (monthly,
  four-weekly double-hit, yearly in/out of period, uncategorized payment
  ignored), savings derivation (fixed bucket per payday, percent bucket
  uses period salary, inactive/unlinked bucket ignored, no-salary case),
  manual-line adoption, stale derived-line removal, frozen past periods,
  idempotency (double refresh = same state).
- API tests: 409 on editing/deleting/creating-over derived lines;
  template-skip on creation; BudgetLineOut.source present.
- Sync tests: source roundtrips; legacy file imports as manual.
- svelte-check 0/0; the 7 known uncategorized.test.ts failures untouched.
