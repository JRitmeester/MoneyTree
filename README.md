# MoneyTree

Personal finance for one household: import your bank's CSV exports, understand
where money goes, and know exactly what to move where on payday.

Two ideas organize the whole app:

- **Cash flow** answers *"where do I move my money so it's in the right place
  at the right time?"* (transfers, timing, payday planning)
- **Budget** answers *"where do I spend my money throughout the month?"*
  (per-category plan vs actual)

Everything else feeds those two questions.

## Quick start

```bash
git clone https://github.com/JRitmeester/MoneyTree.git && cd MoneyTree && docker build -t moneytree . && docker run -d --name moneytree -p 8000:8000 -v "$(pwd)/data:/app/data" -v "$(pwd)/backend/uploads:/app/backend/uploads" moneytree
```

Open http://localhost:8000. On first run the app asks you to create a
username and password in the browser; nothing needs to be configured by
hand. (Env-based configuration for servers is documented in `.env.example`.)

## The flow

**1. Import.** Upload your bank's CSV export (ASN format) on the Import
page. Duplicates are skipped automatically, so re-importing overlapping
exports is safe. Credit-card (ICS) charges appear as one debit; a dashboard
card shows their total so they stay visible.

**2. Categorize.** The Uncategorized page groups unknown transactions by
merchant so one decision categorizes a whole group, and can remember the
mapping for future imports. Categories are hierarchical ("Vaste lasten >
Huur") and managed on the Categories page (create, rename, move, merge).

**3. Clean the picture.** Not every transaction is spending:

- Transfers between your own accounts (register them under Settings >
  Accounts) are detected and excluded from income/expenses.
- One-off events (a holiday, a move) can be marked *incidental*, optionally
  grouped under a label like "Vakantie", so structural spending stays
  readable. Bulk-select on the Transactions page makes this fast.
- Refunds and reimbursements can be linked as *offsets* to the expense they
  cancel, netting out everywhere.
- Receipts can be scanned and split into line items for per-item
  categorization of mixed purchases.

**4. Confirm recurring patterns.** The Recurring page detects repeating
payments (rent, insurance, subscriptions, four-weekly gym, and your salary)
and asks you to confirm or dismiss each. Confirming your salary matters
most: pay-period date filters, the cash-flow calendar, and everything below
depend on it. Give each confirmed payment a category so the budget can use
it.

**5. Move money (Cash flow).** Once the salary is confirmed, the Cash flow
page shows, for each payday:

- **Payday transfer plan**: how much to move to savings to cover every bill
  until the next payday (with a safety buffer), when to move parts back to
  checking, and what must stay in checking for bills that hit right after
  payday. The calculation is fully inspectable.
- **Salary allocation**: divide what's left over configurable buckets
  (fixed amounts or percentages of the remainder) for long-term savings,
  investing, or specific goals, ending in an honest "free to spend" number.
- **Calendar**: which recurring payment hits on which day, weekend- and
  holiday-shifted like your bank actually does it.

**6. Track the month (Budget).** Budget periods hold per-category plans
against actual spending, in four sections: Income, Fixed Bills, Savings
Goals (with running balances per goal), and Flexible Spending. Fixed and
Savings lines maintain themselves from your confirmed recurring payments
and allocation buckets (badged "from recurring" / "from allocation");
only genuinely flexible categories are typed by hand.

**7. Review.** The Dashboard shows the current state (savings capacity,
balance history, recent months); Insights shows the year in review with
per-category comparisons against last year and amortized yearly costs.

Aside from the flow: Settings > Sync exports everything you've created as
one JSON file and imports it elsewhere with a preview, for moving between
devices or seeding a fresh install.

## Development

Backend: FastAPI + SQLAlchemy + SQLite (`backend/`, tests via `pytest`).
Frontend: SvelteKit + Svelte 5 (`frontend/`, `npm run check` and `vitest`).
The Docker image serves the built frontend and runs database migrations on
startup.
