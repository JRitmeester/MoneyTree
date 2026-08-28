# UI Overhaul Plan (UX review wave 4, final)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Make the accumulated features feel like one coherent app: consistent visual system, tidy navigation, uniform states (loading/empty/error), a real mobile pass, and the small deferred polish items from waves 1-3.

## Global Constraints
- No em-dashes anywhere. Conventional commits. svelte-check 0/0; backend 288 tests stay green; the 7 known uncategorized.test.ts failures stay untouched. `rtk proxy` for pytest/vitest.
- No feature changes: behavior-preserving polish only, except where a task lists an explicit copy/logic fix.
- Visual language: keep the existing flat white-card aesthetic and green #2d6a4f accent; centralize, don't redesign.

### Task 1: Design tokens + shared components + deferred polish
**Files:** new `frontend/src/lib/styles/tokens.css` (CSS custom properties for the palette: accent green, income green, expense red, amber, blues, greys, radii; imported once in +layout.svelte); migrate hardcoded hex values in all routes/components to var() tokens (mechanical); extract a shared `PageHeader.svelte` (title + optional right-side slot) used by all pages; consistent `.error` banner component `ErrorBanner.svelte` replacing per-page styles; apply deferred polish: merge-confirm dialog shows all six counts without the stray "..." (categories page), handleAddSub uses extractErrorDetail, standing-buffer advice copy clarified ("included in the sweep, no separate transfer"), yearly-due warning uses the weekend-shifted date (cashflow_advisor.py, small backend change + test tweak), backend salary-picker helper deduplicated into one shared function.
- [ ] One commit `refactor(ui): design tokens, shared header/error components, deferred polish`.

### Task 2: Navigation + page states
**Files:** `frontend/src/routes/+layout.svelte` + nav component; every route page.
**Contract:** Nav grouped and ordered: Overview (Dashboard, Insights), Money (Transactions, Uncategorized, Recurring, Cash flow, Budget), Records (Receipts, Categories, Import), Settings (gear, right-aligned). Active-page highlighting. Every page gets: consistent PageHeader, a real loading state (skeleton or spinner, consistent), a designed empty state with a next-action link (dashboard->import, transactions->import, recurring->rescan/import, budget->create period, receipts->scan, cashflow->confirm salary), and ErrorBanner. No dead ends.
- [ ] One commit `feat(ui): grouped navigation and consistent page states`.

### Task 3: Mobile pass
**Contract:** At 400px width: nav collapses to a hamburger or scrollable pill row (pick the simpler that fits the aesthetic); tables that overflow get horizontal scroll containers or card-collapse (transactions list: hide receipt column, tighten date; budget page usable); bulk bar wraps cleanly and stays sticky; cashflow month grid becomes a vertical agenda list on small screens (simplest correct approach: media query swapping grid for list); dashboard cards stack; tap targets 44px for checkboxes/stars. Verify with svelte-check only (no visual regression tooling exists); document what was changed per page in the report.
- [ ] One commit `feat(ui): mobile layout pass`.

### Task 4: Final verification
- [ ] Backend suite, svelte-check, vitest (7 known), build. Local only.
