# Salary Allocation Plan — Design

Date: 2026-08-28
Status: approved for planning

## Purpose

Each payday, the user wants to divide their salary deliberately: an amount
to the savings account for recurring costs (already computed by the
transfer advisor), amounts to long-term savings and specific saving goals,
an amount to investing, and a clear picture of what genuinely remains free
to spend. This feature computes and displays that division as a plan the
user executes manually at their bank.

Plan-only for now. A later phase will add CSV import from the savings
account and per-bucket tracking; this design must not block that, which is
why buckets are a real synced table with an optional category link rather
than a settings blob.

## Scope

In scope:

- A new `allocation_buckets` table, CRUD API, and sync support.
- A pure allocation calculation service anchored to the current pay
  period.
- `GET /api/cashflow/allocation` returning the computed plan.
- A "Salary allocation" card on `/cashflow` with inline bucket editing.

Out of scope (future phases):

- Tracking actual transfers, per-bucket balances, reconciliation against
  savings-account CSV imports.
- Any automatic execution of transfers.

## Data model

New table `allocation_buckets`:

| Column        | Type                | Notes                                          |
|---------------|---------------------|------------------------------------------------|
| `id`          | int PK              |                                                |
| `name`        | str, non-empty      | Unique (case-sensitive); sync natural key      |
| `rule_type`   | str                 | `"fixed"` or `"percent"`                       |
| `value`       | float               | Euros when fixed (> 0); 0-100 when percent     |
| `position`    | int                 | Calculation and display order, 0-based         |
| `category_id` | int FK, nullable    | Optional link to a category (savings goal); `ON DELETE SET NULL` semantics: deleting or merging the category never deletes the bucket |
| `is_active`   | bool, default true  | Paused buckets are kept but skipped entirely   |

Alembic migration chains from head `o5p6q7r8s9t0`.

Category merge (`/api/categories/{id}/merge-into/{target}`) re-points
`allocation_buckets.category_id` like it re-points other references.
Category delete sets it to NULL.

"Delete everything" wipes `allocation_buckets`.

## Validation rules (write time)

- `name` non-empty after trim; duplicate name → 409.
- `rule_type` must be `fixed` or `percent`.
- Fixed: `value` > 0. Percent: 0 < `value` <= 100.
- Percent cap: if a create/update/activate would make the sum of `value`
  over **active percent** buckets exceed 100, reject with 409 and a
  message naming the current sum. Fixed buckets have no write-time cap
  (overshoot is a runtime shortfall warning, not misconfiguration).

## Allocation calculation

New service `backend/app/services/salary_allocator.py`. Pure function over
inputs fetched by the router; no persistence.

### Anchor: the current pay period

The plan answers "how do I divide the salary I most recently received",
not "what will next month look like". Therefore:

- If the confirmed salary (same `find_salary_payment_id` selection the
  advisor uses) has at least one occurrence: the anchor payday is the
  **latest occurrence date**, and the salary amount is that occurrence's
  **actual amount**. `basis = "actual"`.
- If a confirmed salary exists but has no occurrences: the anchor payday
  is the next expected (shifted) payday and the amount is
  `expected_amount`. `basis = "expected"`.
- If no confirmed salary: same explicit "confirm your salary first" state
  as the advice endpoint.

Stale anchor: when the anchored period has already ended (the next payday
after the anchor is before today), the plan still computes, but `warnings`
gains "This plan is based on the salary received on <date>; a newer salary
may not be imported yet." The UI shows it in the warning box like any
other warning.

### Bills pot for the anchored period

The existing `compute_advice` is strictly forward-looking, so the advisor
gains an anchored variant: `compute_advice(db, buffer_pct, today=...,
anchor_payday=...)` (or an extracted helper both paths share). With an
anchor, the sweep window is `[anchor_payday, next_payday_after(anchor))`
with the same weekend/holiday shifting, clustering, keep-in-checking, and
buffer logic as today. Without an anchor, behavior is unchanged. The
stale-payday roll-forward warning is suppressed in anchored mode (being
"in the past" is the point).

The allocation plan consumes from this anchored advice:

- `bills_pot` = the anchored `sweep_amount` (buffer included).
- `kept_in_checking` = the anchored `keep_in_checking`.

### Waterfall

Given `salary` (absolute), ordered active buckets, `bills_pot`,
`kept_in_checking`:

1. `remaining = salary - bills_pot - kept_in_checking`. If this is already
   negative, clamp every bucket to 0, set the free amount to 0, and warn
   that the salary does not cover the recurring bills.
2. Fixed buckets in `position` order: each gets
   `min(bucket.value, remaining)`; `remaining` decreases. The first bucket
   that receives less than its configured value (including 0) triggers one
   shortfall warning naming that bucket.
3. `percent_base = remaining` after all fixed buckets. Each percent bucket
   gets `floor_to_cent(percent_base * value / 100)`. All percent buckets
   share the same base, so they cannot overshoot it (write-time cap keeps
   the sum <= 100).

   `shortfall` is a fixed-bucket concept only: a fixed bucket is
   shortfalled when it receives less than its configured value. Percent
   buckets are never marked shortfalled; receiving a small amount because
   the remainder is small is their rule working as configured
   (`shortfall` is always `false` on percent lines).
4. `free_to_spend = salary - bills_pot - kept_in_checking - sum(all
   bucket amounts)`. Rounding leftovers from the floor therefore land in
   `free_to_spend`, and all displayed rows sum exactly to `salary`.

All amounts rounded to cents; no row is ever negative.

## API

### `GET /api/cashflow/allocation`

Response (`SalaryAllocationOut`):

```json
{
  "salary_confirmed": true,
  "message": null,
  "payday": "2026-08-24",
  "basis": "actual",
  "salary_amount": 3166.17,
  "bills_pot": 2208.80,
  "kept_in_checking": 40.00,
  "lines": [
    {"bucket_id": 1, "name": "Long-term savings", "rule_type": "percent",
     "value": 50.0, "amount": 458.68, "category_id": 12,
     "category_name": "Sparen > Lange termijn", "shortfall": false}
  ],
  "free_to_spend": 458.69,
  "warnings": []
}
```

`salary_confirmed: false` mirrors the advice endpoint's shape (message
set, everything else null/empty). Inactive buckets are omitted from
`lines`.

### Bucket CRUD (`/api/allocation-buckets`)

- `GET /` — all buckets (active and paused), ordered by `position`.
- `POST /` — create; appended at the end (`position = max + 1`).
- `PATCH /{id}` — partial update of `name`, `rule_type`, `value`,
  `category_id`, `is_active` (uses `exclude_unset`, explicit-null
  clears `category_id`).
- `DELETE /{id}` — hard delete; remaining positions re-compacted.
- `PUT /order` — body `{"ids": [3, 1, 2]}`, the complete list of bucket
  ids in the new order; 400 if the set doesn't exactly match existing
  buckets. Positions rewritten 0..n-1 server-side.

All under the existing auth dependency.

## Sync

Export `format_version` stays 3; `ExportFile` gains an optional
`allocation_buckets: list[ExportAllocationBucket] =
Field(default_factory=list)` section, the same pattern used when
`incidental_labels` and `own_accounts` were added. Verified: `ExportFile`
is a default pydantic model, so older importers ignore the unknown key and
files without the section parse with an empty list.

Each entry: `{name, rule_type, value, position, is_active,
category_path}` with `category_path` the " > " path or null, resolved on
import exactly like other category references (creating missing ancestors
per the v3 rules). Import upserts by `name`: existing bucket with the same
name is updated, others created; buckets present locally but absent from
the file are left alone (consistent with how labels/own accounts import).
Files without the section import as today.

Position normalization: imported positions are treated as relative order
only, never written verbatim. After the upsert, all buckets are re-sorted
(imported buckets in the file's order first, then local-only buckets in
their existing relative order) and positions rewritten 0..n-1, so
duplicates and gaps cannot occur.

## UI

On `/cashflow`, a new section below the payday transfer plan:

**View mode** — title "Salary allocation", subtitle naming the payday and
basis ("Salary received Fri 23 Aug" vs "Expected salary, not yet
received"). A waterfall list:

1. "Recurring bills pot" row (the anchored `bills_pot`; muted, captioned
   "covers bills until next payday"). Do NOT annotate it as equal to the
   advice card's transfer figure: the advice card is forward-looking
   (next payday) while this card is anchored to the current period, so
   the two amounts legitimately differ late in a pay period.
2. "Kept in checking for imminent bills" row when nonzero (muted).
3. One row per active bucket: name, computed euro amount, muted rule
   caption ("fixed" / "50% of remainder"), linked category name when set,
   amber highlight + note when shortfalled.
4. "Free to spend" row, bold.

Warnings render in the same amber `warning-box` style as the advice card.
Empty state (no buckets yet): one-paragraph explanation plus an "Add your
first bucket" button that opens edit mode.

**Edit mode** — toggled by an "Edit buckets" button. Inline rows: name
input, rule-type select, value input (with € or % adornment), CategoryInput
for the optional goal link, pause/resume, delete (confirm dialog), drag or
up/down buttons for reordering (up/down buttons are sufficient; call
`PUT /order` with the full id list). Auto-save on blur/Enter like the
budget page; 409s surface via `extractErrorDetail`. Adding a bucket
appends an empty row saved on first valid blur.

No confirmed salary: the section shows the same "confirm your salary
first" empty state as the advice card (single link to /recurring; don't
render two identical cards saying the same thing — if the advice card
already shows it, the allocation section is simply omitted).

## Error handling

- All endpoints return friendly `detail` messages; the frontend surfaces
  them through `extractErrorDetail` into `ErrorBanner` (page-level) or
  inline next to the offending row in edit mode.
- The allocation endpoint never 500s on odd data: zero-amount salary
  occurrence falls back to `expected_amount` with a warning; missing
  buffer setting uses `DEFAULT_BUFFER_PCT`.

## Testing

- `test_salary_allocator.py` (TDD): fixed+percent mix summing exactly to
  salary; percent flooring with leftover absorbed by free_to_spend;
  shortfall fills fixed buckets in position order and warns on the first
  unfunded one; salary below bills pot clamps to zero with warning;
  inactive buckets skipped; actual-vs-expected basis selection; anchored
  advice window equals [anchor, next payday).
- `test_allocation_api.py`: CRUD, percent-cap 409, duplicate-name 409,
  reorder happy path + mismatched-ids 400, delete re-compaction,
  allocation endpoint shape for confirmed/unconfirmed salary.
- Sync tests: export contains the section; import upserts by name and
  resolves `category_path`; legacy file without the section unaffected.
- svelte-check 0/0; the 7 known uncategorized.test.ts failures stay
  untouched.
