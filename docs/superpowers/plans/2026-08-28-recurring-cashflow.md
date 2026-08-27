# Recurring & Cashflow Implementation Plan (UX review wave 3; spec phases 4-6)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Implement spec phases 4-6 from docs/superpowers/specs/2026-08-27-financial-insights-design.md (recurring-payment detection with suggest/confirm, cash-flow calendar, transfer advisor), plus salary-anchored date presets, savings-capacity projection, year-in-review, and an ICS blind-spot line.

**Architecture:** Exactly as the spec's "Data model" and "Recurring-payment detection" sections define: `recurring_payments` + `recurring_payment_occurrences` tables, detector service with named constants, matching on import, notices computed on read. Calendar/advisor per the spec's "Cash-flow calendar and transfer advisor" section.

**Spec:** docs/superpowers/specs/2026-08-27-financial-insights-design.md is the binding authority for tasks 1-5. Its details override this plan on conflict.

## Global Constraints

- No em-dashes. Conventional commits, no attribution footer. TDD with RED evidence.
- Backend baseline 193 tests stays green; svelte-check 0/0; the 7 known uncategorized.test.ts failures stay untouched.
- `rtk proxy` prefix for pytest/vitest output accuracy.
- Alembic head is currently l2m3n4o5p6q7; new migration chains from it.
- Briefs are contracts; read the spec section named in each task before coding.

---

### Task 1: Recurring data model + detector service (spec: "Data model" for the two new tables + "Recurring-payment detection")
**Files:** models.py + migration; `backend/app/services/recurring_detector.py` (thresholds as module constants); tests `backend/tests/test_recurring_detector.py`.
**Contract:** Tables exactly per spec (recurring_payments incl. is_income, status suggested/confirmed/dismissed; occurrences with unique transaction_id). Detector: group non-internal transactions by counterparty_iban else normalized merchant; cadence rules monthly/four_weekly/yearly incl. the drift rule and occurrence minimums; amount rule (75% within 15% of median); upsert suggested rows only, never touching confirmed/dismissed. Pure functions where possible. Fixtures covering: monthly stable day, 4-weekly drift (Basic-Fit pattern), yearly with 2 occurrences, rent increase staying one candidate, settlement outliers flagged-not-disqualifying (outlier flag can be computed, not stored), salary as recurring income.
- [ ] TDD; implement; suite; commit `feat(recurring): data model and detection service`.

### Task 2: Recurring API + import-time matching + notices (spec: "Recurring-payment detection" lifecycle paragraph)
**Files:** `backend/app/routers/recurring.py` (list by status, confirm, dismiss, PATCH edit, rescan, occurrences), transactions import hook, main.py registration, schemas; tests `backend/tests/test_recurring_api.py`.
**Contract:** Confirm backfills occurrences from history; new imports match confirmed patterns (group key + amount tolerance + date within 5 days) appending occurrences and updating anchor_date/expected_amount drift; notices (amount_changed, possibly_missed) computed on read via a `GET /api/recurring/notices` endpoint; detector runs after every import and on POST /api/recurring/rescan. Delete-everything wipes the new tables.
- [ ] TDD; implement; suite; commit `feat(recurring): lifecycle API, import matching, notices`.

### Task 3: Recurring frontend (spec: UI section; controller UX below)
**Files:** `frontend/src/routes/recurring/+page.svelte`, api.ts bindings, nav link (find the app's nav component), dashboard notices badge.
**Contract:** Page with two sections: Suggested (confirm/dismiss buttons, shows name/amount/cadence/expected day/last seen, editable name+category on confirm via inline fields) and Confirmed (same info + next expected date + notices inline + dismiss/pause via PATCH status). Notices badge on the dashboard linking to /recurring when any notice exists. Salary rows highlighted (is_income) since the advisor depends on them.
- [ ] Implement, check 0/0, commit `feat(frontend): recurring payments page and notices`.

### Task 4: Salary-anchored periods + capacity projection (spec: savings-capacity "current-month projection" note)
**Files:** `backend/app/routers/cashflow.py` (start it with a `GET /api/cashflow/periods` endpoint deriving pay periods from the confirmed salary's occurrences: list of {start, end, label} for the last N periods + current), DateRangeFilter.svelte gains a "Pay periods" preset group (This/Last/-2/-3) shown only when periods exist (fetch once, cache in the dateRange store module), savings-capacity endpoint fills current_month_projection using confirmed recurring payments due before month-end; tests extend test_dashboard_insights.py + new test_cashflow.py.
**Contract:** A pay period runs from one salary occurrence date (inclusive) to the day before the next (or today+open for the current one). No confirmed salary: endpoint returns [], UI hides the presets, projection stays null.
- [ ] TDD; implement; suite + check; commit `feat(cashflow): salary-anchored periods and capacity projection`.

### Task 5: Cash-flow calendar + transfer advisor (spec: "Cash-flow calendar and transfer advisor", binding)
**Files:** cashflow.py (calendar + advice endpoints per spec incl. buffer_pct setting stored in a new tiny `app_settings` key-value table with migration OR reuse an existing settings mechanism if one exists: check first), `frontend/src/routes/cashflow/+page.svelte` (month grid + advice card + warnings), api.ts, nav link; tests test_cashflow.py.
**Contract:** Exactly the spec's three advisor outputs (sweep amount, at most two monthly return transfers with the 2-business-day rule and 4-weekly handling, warnings list incl. pre-payday debits and yearly items). Advisor with no confirmed salary returns the explicit "confirm your salary first" state.
- [ ] TDD (advisor math cases: the user's real pattern: rent cluster on 1st, bills cluster 20th-29th, salary ~22nd); implement; suite + check; commit `feat(cashflow): calendar and transfer advisor`.

### Task 6: Year in review + amortized view + ICS line (extras)
**Files:** dashboard.py (`GET /api/dashboard/year-review?year=` returning per-root-category totals for the year and the previous year for comparison, plus income/expense/net per year), SavingsCapacityPanel or a new `/insights` page section for it (controller choice: new route `/insights` with year selector, category table with delta column, and an "amortized yearly costs" block: confirmed yearly recurring payments divided by 12 shown as monthly equivalent), plus dashboard summary card "ICS/credit card" showing the period's total debits whose merchant/naam matches ICS (config-free heuristic: counterparty name containing "International Card Services" or merchant containing "ICS"), only when nonzero; tests.
**Contract:** Year-review math tested; ICS heuristic tested; amortized block only lists confirmed yearly recurring payments.
- [ ] TDD; implement; suite + check; commit `feat(insights): year in review, amortized yearly costs, ICS visibility`.

### Task 7: Final verification
- [ ] Full backend suite; check; vitest (7 known failures only); `npm run build`. Local only; no deploy, no push.
