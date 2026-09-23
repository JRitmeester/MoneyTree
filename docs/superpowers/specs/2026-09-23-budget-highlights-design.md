# Budget Highlights — Design

Date: 2026-09-23
Status: approved direction (deterministic rule engine, no AI), spec for review

## Purpose

Reviewing a closed budget period currently requires walking the Actuals tab
with a method in your head (normalize the headline, hunt fixed ghosts, one
sentence per flexible outlier, check savings execution). This feature
encodes that method as a fixed catalog of deterministic rules and renders
the result as a Highlights panel: same data in, same cards out, every time.
No generated language; every card is a fixed template with numbers filled
in. The user's review becomes: read the cards, click anything amber they
cannot explain.

## Data sources (all existing)

- The budget's lines (plan, source, category_type) and the budget-vs-actual
  computation (actuals per category, savings contributions, income lines).
- The period's transactions (for incidental normalization, the one-off
  detector, top expenses, and pot withdrawals).
- Incidental labels (per-label totals within the period).

Period date convention is half-open `[start_date, end_date)`; every
transaction query uses `datum >= start AND datum < end` (or the inclusive
equivalent with end minus one day, matching the budget-vs-actual fix of
2026-09-23).

## API

`GET /api/budgets/{budget_id}/highlights` (auth-required, 404 on unknown
id). Response:

```json
{
  "budget_id": 1,
  "start_date": "2026-08-21",
  "end_date": "2026-09-23",
  "closed": true,
  "summary": {
    "raw_net": -1579.82,
    "incidental_total": 1432.80,
    "incidental_by_label": [{"label": "Vakantie", "amount": 632.80}],
    "unlabeled_incidental": 800.00,
    "structural_net": -147.02,
    "flexible_within_plan": 8,
    "flexible_total": 11,
    "pots_executed": 0,
    "pots_planned": 9
  },
  "highlights": [
    {
      "rule": "fixed_ghost",
      "severity": "warn",
      "title": "Internet: no payment occurred",
      "detail": "Planned EUR 149.96, nothing arrived. Check the Recurring page for a stale payment.",
      "category_id": 12,
      "amount": 149.96
    }
  ]
}
```

- `severity` is one of `good | info | warn`.
- `highlights` ordering is deterministic: catalog order of the rules below,
  then descending absolute `amount`, then `category_id` ascending.
- `closed` is `end_date <= today`. Open periods run a reduced catalog (per
  rule below); the UI labels the panel "so far" when open.
- All amounts rounded to cents; all copy from fixed templates (exact
  strings live in the implementation and its tests; the templates in this
  spec are normative for meaning, not for byte-exact wording).

## Rule catalog

Constants (module-level, tested):
`OVERRUN_PCT = 0.20`, `OVERRUN_MIN_EUR = 25.0`, `UNDERRUN_FRACTION = 0.5`,
`ONE_OFF_FRACTION = 0.5`, `BILL_INCREASE_FACTOR = 1.10`,
`SALARY_CHANGE_PCT = 0.02`, `TOP_EXPENSES_COUNT = 3`,
`CLIMATE_PERIODS = 3`.

### R1: honest headline (summary block, always)

`raw_net` = actual income minus actual CONSUMPTION: expense-line actuals
excluding savings-type lines (whose "actual" is a net transfer flow, not
spending, since 2026-09-23). Savings flows surface only through R6.
`incidental_by_label` = per-label net spend (expenses minus incidental
income) of incidental transactions in the period; `unlabeled_incidental`
covers incidental transactions without a label. `structural_net` =
raw_net + incidental_total. Not a card; it feeds the summary header.

### R2: fixed ghost (closed only; severity warn)

For each Fixed-section line (expense line with source "recurring", or
manual with is_fixed): actual == 0 and plan > 0 → "no payment occurred,
check the Recurring page". One card per line.

### R3: bill increased / decreased (closed only; info)

Fixed-section line with actual > plan * BILL_INCREASE_FACTOR → "this bill
came in EUR X above plan". Actual > 0 and actual < plan / BILL_INCREASE_FACTOR
→ "this bill came in EUR X below plan". Skip lines already covered by R2.

### R4: flexible overrun (closed only; warn)

Flexible line (manual, not is_fixed, expense-type) with
actual - plan > max(plan * OVERRUN_PCT, OVERRUN_MIN_EUR) → card. The
one-off detector augments the detail: if a single transaction in that
category (descendants included, matching how actuals aggregate) is >=
ONE_OFF_FRACTION of the category's actual, the card names it
("largely one purchase: <merchant> EUR X on <date>").

### R5: flexible strong underrun (closed only; info)

Flexible line with plan > 0 and actual < plan * UNDERRUN_FRACTION →
"well under plan". At most the single largest such card (by unspent
amount) to avoid noise.

### R6: savings execution (always; severity varies)

Per savings-type line with plan > 0, using the contributed amount (net
internal transfers into the pot, as budget-vs-actual computes since
2026-09-23):
- contributed >= plan → good ("pot funded").
- contributed == 0 and closed → warn ("no transfer categorized to this pot:
  either it was not made, or the transaction is not categorized yet").
- contributed == 0 and open → info (same text, "yet" framing).
- contributed < 0 → warn ("net withdrawal of EUR X"), detail lists up to 3
  contributing transfer transactions (date + amount + counterparty name).
- 0 < contributed < plan → info ("partially funded, EUR X of EUR Y").
Emit at most one aggregate good card when ALL planned pots are funded,
instead of one card per funded pot; warn/info cards stay per pot.

### R7: income change (fires once salary actual > 0; info, good when up)

Income line with |actual - plan| > plan * SALARY_CHANGE_PCT → "income came
in EUR X above/below plan". With multiple income lines, evaluate each.

### R8: top expenses (always; info, single card)

The TOP_EXPENSES_COUNT largest non-incidental, non-internal-transfer
expense transactions of the period, one card listing them (merchant,
amount, date, category). Deterministic tie-break: amount, then datum, then
transaction id.

### R9: scorecard (closed only; info, single card)

"N of M flexible categories within plan; savings plan X of Y pots
executed." Within plan = not flagged by R4. Executed = contributed >= plan.
The same numbers appear in `summary`.

### R10: climate detection (DEFERRED, v1.1)

Same flexible category flagged by R4 in CLIMATE_PERIODS consecutive closed
periods → warn "structural overrun: raise the line or change the habit".
Deferred until at least three closed periods exist; the spec records the
rule so v1 code leaves an obvious seam (rules receive prior periods'
flagged sets as an input that v1 passes empty).

### Subtree aggregation (applies to R4, R5, R9)

Budget-vs-actual lines are per exact category, but flexible plan lines
often sit on a parent (plan on "Vrije Tijd", actuals on its children). For
these rules, a flexible line's effective actual is the sum of the actuals
of its category and every descendant category that does not carry its own
plan line in this budget (a descendant with its own line is judged on its
own and excluded from the parent's aggregate). The one-off detector
searches transactions across the same descendant set.

## Determinism guarantees

- No randomness, no model calls, no wall-clock dependence except `today`
  for the `closed` flag (injectable in tests).
- Pure function `compute_highlights(db, budget, today) -> HighlightsResult`
  in a new `backend/app/services/budget_highlights.py`; the endpoint only
  maps it to the response schema.
- Rules never raise per-line: a rule that errors on one line logs and skips
  it (mirrors budget derivation's error posture).

## UI

Actuals tab, above the Income section: a "Highlights" block.

- Header row: structural net (bold), raw net with the incidental breakdown
  as a muted caption, and the scorecard counts. Open periods append
  "(period in progress)".
- Cards below in returned order: severity accent (green/neutral/amber left
  border, reusing the existing warn/ok palette), title, detail, and, when
  `category_id` is present, the whole card links to
  `/spending/category/{id}` with the period's inclusive dates (same link
  plumbing as the row links).
- Empty highlight list (all quiet, e.g. a fresh open period): one neutral
  line "Nothing notable yet."
- Mobile: cards stack full-width; tap targets are the full card.

## Error handling

- Endpoint 404s on missing budget; otherwise never 500s for data reasons
  (skip-and-log per rule).
- Frontend failures show the page's ErrorBanner; the Actuals tables render
  independently of the Highlights block.

## Testing

- Unit tests per rule against synthetic periods (RED first): ghost fires
  only when closed; overrun threshold boundaries (exactly at max(20%, 25)
  does not fire, one cent over does); one-off detector at the 50% boundary;
  savings execution all five branches; withdrawal card lists transactions;
  income change both directions; top-3 ordering and tie-breaks; scorecard
  counts consistent with fired rules; ordering of the full list; open vs
  closed catalogs; incidental normalization with labeled + unlabeled mixes
  and incidental income.
- API test: shape, 404, closed flag.
- svelte-check 0/0; the 7 known uncategorized.test.ts failures untouched.
