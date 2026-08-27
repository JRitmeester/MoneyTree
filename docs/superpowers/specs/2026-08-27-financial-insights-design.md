# Financial Insights: Transfers, Recurring Payments, Savings Capacity, Cash Flow

Date: 2026-08-27
Status: Approved design, pending implementation plan

## Goal

Give the user a full grip on spending and a trustworthy answer to "how much can
I save each month", and automate the analysis currently done by hand on bank
CSVs: identifying vaste lasten and subscriptions, their payment-date patterns,
and a savings-account transfer schedule around payday.

## Scope and constraints

- Data source stays the ASN checking-account CSV only. The savings account is
  never imported; its balance is inferred. The credit card account is out of
  scope for now (statements exist as monthly PDFs, 21st to 20th; a future
  feature).
- One checking account, one savings account.
- Recurring detection is suggest-then-confirm: the user confirms or dismisses
  every detected pattern before the app relies on it.
- One-off expenses are excluded from structural numbers via a manual
  per-transaction `is_incidental` flag (bulk-settable), not per-category and
  not purely statistical.
- The cash-flow feature includes a transfer-schedule advisor, not just a
  calendar. The user's bank supports recurring transfers weekly, every 4
  weeks, or monthly.

## Architecture overview

Approach chosen: persisted entities with a suggest/confirm lifecycle
(rejected: compute-on-read with no recurring table, because confirmations need
a stable anchor and history tracking; rejected: generalized forecasting
engine, YAGNI).

Six features, in build order:

1. Own accounts + internal transfer flagging (fixes every existing number)
2. Balance-over-time chart from `saldo_voor_boeking`
3. Savings-capacity view (monthly net excl. transfers, incidentals excluded,
   trailing averages, current-month projection)
4. Recurring-payment detection with cadence and next-expected-date
5. Cash-flow calendar
6. Transfer-schedule advisor

## Data model

New table `own_accounts`:

- `iban` (unique string), `name`, `account_type` (`checking` | `savings`),
  `starting_balance` (float, savings only; balance as of `starting_balance_date`),
  `starting_balance_date` (date, nullable), `created_at`.
- Seeded via settings UI; checking IBAN auto-suggested from
  `transactions.rekening`.

New table `recurring_payments`:

- `merchant_pattern` (normalized merchant string), `counterparty_iban`
  (nullable; strongest match key when present), `name` (editable display
  name), `expected_amount`, `amount_tolerance` (fraction, default 0.15),
  `cadence` (`monthly` | `four_weekly` | `yearly`), `expected_day`
  (day-of-month; null for four_weekly), `anchor_date` (last known occurrence;
  drives four-weekly projection), `status`
  (`suggested` | `confirmed` | `dismissed`), `category_id` (nullable FK),
  `is_income` (bool; salary is tracked as recurring income and drives the
  advisor), `created_at`, `updated_at`.

New table `recurring_payment_occurrences`:

- `recurring_payment_id` FK, `transaction_id` FK (unique), `amount`, `date`.
- Separate table (not a flag on transactions) so a detector re-run can rebuild
  it without touching transaction rows. Powers next-expected, amount-change
  detection, and missed-payment notices.

New columns on `transactions`:

- `is_internal_transfer` (bool, default false)
- `is_internal_transfer_manual` (bool, default false; set when the user
  overrides, so backfills never clobber a manual decision)
- `is_incidental` (bool, default false)

Alembic migrations create the tables/columns and backfill
`is_internal_transfer` for existing history once own accounts exist.

No changes to categories, budgets, or receipts.

## Internal transfers and savings balance

Detection: on CSV import, and on backfill whenever an own account is added or
edited, set `is_internal_transfer = true` where `tegenrekening` matches an
own-account IBAN. Backfill skips rows with `is_internal_transfer_manual`.
Manual override via PATCH + toggle on the transaction detail page.

Effect on existing numbers: `dashboard/summary`, `by-category`,
`monthly-trend`, and `budget-vs-actual` exclude internal transfers from income
and expenses. The dashboard summary gains a separate "Transfers" line (net
moved to/from savings in the period) so money never silently disappears.

Inferred savings balance:
`starting_balance + sum(transfers to savings since starting_balance_date)
- sum(transfers from savings since starting_balance_date)`, from flagged
transactions whose counterparty is the savings account. Shown on the dashboard
and used by the advisor.

Balance history: `GET /dashboard/balance-history` returns a daily
checking-balance series for a date range from `saldo_voor_boeking` +
`bedrag`; where multiple transactions share a day, the last by `volgnummer`
wins. Rendered as a line chart on the dashboard.

## Recurring-payment detection

Grouping: non-internal transactions, keyed by `counterparty_iban` when
present, else by normalized `merchant_name` (lowercased, terminal numbers
stripped, reusing the merchant extractor's normalization). Income and expenses
both scanned.

Cadence, for groups with enough occurrences, from gaps between consecutive
dates:

- median gap 26 to 36 days, day-of-month stable within plus or minus 4:
  `monthly`, `expected_day` = median day-of-month (needs 3+ occurrences)
- median gap 26 to 30 days with consistently drifting day-of-month:
  `four_weekly`, anchored on last occurrence (needs 3+ occurrences)
- median gap 350 to 380 days: `yearly` (needs 2 occurrences)
- anything else: not a candidate

Amount: candidate qualifies if at least 75% of occurrences fall within 15% of
the median amount. Outliers (e.g. an energy settlement month on an otherwise
stable pattern) are flagged on the occurrence, not disqualifying.

Lifecycle:

- Detector runs after every CSV import and on demand ("re-scan" button).
  Upserts `suggested` rows only; never touches `confirmed` or `dismissed`.
- Confirm backfills occurrences from history.
- New imports are matched against confirmed patterns (same group key, amount
  within tolerance, date within plus or minus 5 days of expected): match
  appends an occurrence and updates `anchor_date` and `expected_amount`
  drift; a deviating amount raises an "amount changed" notice; an expected
  date passing 5+ days unmatched raises a "possibly missed or cancelled"
  notice. Notices are computed on read; no notifications table.
- Detection thresholds are named constants in
  `backend/app/services/recurring_detector.py`.

## Savings-capacity view

`GET /dashboard/savings-capacity?months=N` (default 6), per calendar month,
always excluding internal transfers:

- `income`, `expenses_total`, `expenses_structural` (excl. `is_incidental`),
  `net_raw`, `net_structural`
- fixed vs flexible split of structural expenses via the category's
  `is_fixed`; uncategorized is its own visible bucket
- trailing 3- and 6-month averages of both net numbers; headline =
  trailing-6 `net_structural`
- current-month projection: actuals to date plus remaining expected recurring
  payments due before month-end (null until confirmed recurring payments
  exist, since this is built one phase earlier than recurring detection)
- partial months (not fully covered by imported data) are excluded from
  averages

UI: savings section on the dashboard with monthly bars (income, structural
expenses, net), the trailing averages, and per-month incidental totals shown
separately.

## Cash-flow calendar and transfer advisor

Calendar: `GET /cashflow/calendar?month=YYYY-MM` projects confirmed recurring
payments into the month: monthly/yearly on `expected_day` shifted to the next
business day when it falls on a weekend; four-weekly stepped from
`anchor_date`. Returns per-day expected debits/credits plus salary date. UI:
month grid highlighting cluster windows.

Advisor: `GET /cashflow/advice` computes from confirmed recurring payments
(salary included):

1. Sweep amount on payday: all recurring debits due before the next payday,
   plus a configurable buffer percentage (`buffer_pct` setting).
2. Return transfers: greedy clustering of expected debits into at most two
   monthly recurring transfer dates (options: weekly / four-weekly /
   monthly), such that money arrives 2+ business days before the earliest
   debit covered, minimizing average days idle in checking. Four-weekly
   debits are covered by a matching four-weekly transfer or, below an amount
   threshold, folded into a standing-buffer recommendation, whichever wins.
3. Warnings: debits landing before payday, amount drift since last view,
   yearly items due in the coming month.

Advice is computed on read; only `buffer_pct` is persisted.

## API surface

New routers:

- `own_accounts.py`: CRUD `/own-accounts`
- `recurring.py`: `GET /recurring?status=`, `POST /recurring/{id}/confirm`,
  `POST /recurring/{id}/dismiss`, `PATCH /recurring/{id}`,
  `POST /recurring/rescan`, `GET /recurring/{id}/occurrences`
- `cashflow.py`: `GET /cashflow/calendar`, `GET /cashflow/advice`

Extended:

- `dashboard.py`: `/balance-history`, `/savings-capacity`, transfers-aware
  summary
- `transactions.py`: PATCH gains `is_incidental` and `is_internal_transfer`;
  new bulk-incidental endpoint

## UI

- `/settings/accounts`: own accounts, savings starting balance + date,
  buffer percentage
- `/recurring`: suggested vs confirmed lists, confirm/dismiss/edit, notices
- `/cashflow`: calendar + advice card
- Dashboard: balance chart, savings-capacity section, transfers summary line,
  notices badge
- Transactions list: incidental toggle, internal-transfer indicator

## Error handling

- Import remains transactional per file; transfer flagging failures never
  block an import (row imports unflagged, backfill catches it).
- Advisor with no confirmed salary pattern returns an explicit
  "confirm your salary as recurring income first" state, not a guess.
- Savings balance without a starting balance shows "net transferred" labeled
  as such, not as a balance.

## Testing

Backend pytest:

- detector heuristic: fixtures with monthly, four-weekly drifting, yearly,
  rent-increase, and settlement-outlier patterns
- transfer flagging, backfill, and manual-override protection
- savings-capacity math incl. incidentals and partial-month exclusion
- advisor scheduling incl. debits landing before payday

Frontend component tests for the recurring confirm flow, following the
existing `uncategorized.test.ts` pattern. This begins analytics test coverage
that is currently absent.

## Build order (implementation phases)

1. Own accounts + transfer flagging + dashboard exclusion + transfers line
2. Balance-over-time chart
3. Incidental flag + savings-capacity endpoint and dashboard section
4. Recurring detection service + `/recurring` page + import-time matching
5. Cash-flow calendar
6. Transfer advisor

Each phase is independently shippable and useful.
