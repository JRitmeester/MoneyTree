# MoneyTree User Manual

MoneyTree is a personal finance application that helps you track spending, categorize transactions, attach receipts, and plan monthly budgets. It imports bank statements from ASN Bank CSV exports and provides dashboards to understand where your money goes.

## Getting Started

### Running with Docker (recommended)

```bash
docker compose up --build
```

Open **http://localhost:8080** in your browser.

Your data is stored in `./data/moneytree.db` and receipt images in `./backend/uploads/`, both mounted as Docker volumes so they persist across restarts.

### Running locally (development)

Prerequisites: Python 3.12+, Node.js 20+

```bash
# Backend
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# Frontend
cd frontend && npm install && npm run build && cd ..

# Start
uvicorn backend.app.main:app --port 8080
```

Open **http://localhost:8080**.

---

## Importing Transactions

This is typically the first thing you do. MoneyTree reads CSV exports from ASN Bank.

### Exporting from ASN Bank

1. Log into your ASN Bank online banking
2. Go to your transaction history
3. Select the date range you want to export
4. **Important**: Check the option to include the "Categorie" (category) column — this gives each transaction a bank-assigned category like "Boodschappen", "Salaris", etc.
5. Download the CSV file

### Importing into MoneyTree

1. Navigate to **Import** in the top menu
2. Drag your CSV file onto the drop zone, or click to select it from your computer
3. The file name appears with a green checkmark when selected
4. Click **Import**

After importing, you'll see a summary:
- **Imported**: Number of new transactions added
- **Skipped (duplicates)**: Transactions that were already in the system (matched by a hash of date, account number, sequence number, and statement number)
- **Matched receipts**: Receipts that were automatically linked to transactions

If MoneyTree finds receipts that might match imported transactions, it shows a confirmation dialog where you can accept or reject each suggested match.

### Re-importing with updates

If you previously imported a CSV without the category column (all transactions got the default category "Overig"), you can re-import:

1. Export a new CSV from ASN Bank with the category column enabled
2. On the Import page, check **"Update existing transactions"**
3. Import the new file

This overwrites the data on matching transactions with the new CSV's values, including the category. The checkbox description explains: "Overwrite previously imported transactions with data from this file."

---

## Dashboard

The Dashboard (home page) gives you a financial overview of a selected time period.

### Date range

A date range filter at the top right lets you pick a time window. Quick-select buttons are available:

| Button | Period |
|--------|--------|
| 1W | Last 1 week |
| 2W | Last 2 weeks |
| 1M | Last 1 month (default) |
| 2M | Last 2 months |
| 3M | Last 3 months |
| 6M | Last 6 months |
| 1Y | Last 1 year |

You can also set custom dates using the date pickers next to the preset buttons.

### Summary cards

Five cards at the top show:
- **Income**: Total money received (positive transactions)
- **Expenses**: Total money spent (negative transactions)
- **Net**: Income minus expenses
- **Transactions**: Number of transactions in the period
- **Receipts**: Number of receipts attached to transactions in the period

### Spending by Category

A bar chart breaks down your expenses by bank category. Click any category to expand it and see:
- **Line-item subcategories** (if receipts with categorized line items are attached)
- A **"View N transactions"** link that takes you to the Transactions page filtered by that category and date range

### Monthly Trend

A table showing income, expenses, and net for each of the last 12 months.

---

## Transactions

The Transactions page lists all imported transactions with search, filtering, and pagination.

### Filtering

- **Search**: Type in the search box to filter by description, merchant name, or counterparty name (debounced, searches as you type)
- **Category**: Filter by bank category name
- **Date range**: Same quick-select presets as the Dashboard (defaults to last 1 month)

### Pagination

- Use Previous/Next buttons to navigate pages
- A dropdown lets you choose page size: 20, 50, 100, 200, or 500 transactions per page
- Transactions are sorted by date (newest first)

### Date dividers

A subtle grey line separates transactions from different dates, making it easy to see day boundaries.

### Transaction detail

Click any transaction row to see its full details:

- **Amount and merchant** at the top
- **Category selector**: A dropdown showing all your categories (including subcategories, indented). Select a different category to re-categorize the transaction — it saves immediately.
- **Description, counterparty IBAN, type, processing date, balance before**
- **Receipt**: Link to the attached receipt, if any
- **Line Items**: A detailed breakdown of what was purchased (see Line Items section below)

---

## Receipts

The Receipts page shows a grid of all uploaded receipt images.

### Uploading a receipt

1. Navigate to **Receipts** and click **+ Add Receipt**, or go directly to **/receipts/new**
2. Select or drag an image of your receipt
3. MoneyTree runs OCR (optical character recognition) to extract:
   - Date
   - Total amount
   - Merchant name
   - Individual line items (product descriptions and prices)
4. Review the extracted data and correct any OCR errors
5. Confirm to save

After uploading, MoneyTree automatically tries to match the receipt to an unlinked transaction based on amount, date proximity, and merchant name similarity.

### Receipt cards

Each receipt shows a thumbnail, merchant name, date, amount, and a status:
- **Linked** (green): Matched to a transaction
- **Unmatched** (amber): No transaction linked yet

Use the **"Unmatched only"** checkbox to filter for receipts that still need linking.

If a receipt image can't be loaded (e.g., the file was moved), a grey placeholder is shown instead.

### Linking receipts to transactions

Receipts can be linked to transactions in three ways:
1. **Automatically** during import or upload (high-confidence matches)
2. **Semi-automatically** via the confirmation dialog after import (medium-confidence matches)
3. **Manually** from the receipt detail page — click Link and select a transaction

---

## Line Items

Line items are the detailed breakdown of a transaction — the individual products or services that make up the total. They can come from OCR on a receipt or be added manually.

### Adding line items

On a transaction detail page, click **"Add items"** (or **"Edit"** if items already exist):
1. Enter a description and amount for each item
2. Assign categories using the category input field
3. Click **Save**

If the transaction doesn't have a receipt, MoneyTree automatically creates a virtual receipt to hold the line items.

### Category input

The category input field supports:

- **Autocomplete**: Start typing to see matching existing categories and Category table entries
- **Multiple tags**: Each line item can have multiple categories (shown as tags, separated by commas)
- **Hierarchical categories**: Type with `>` to create subcategories, e.g. `Hardware Store > Paint` creates "Paint" as a subcategory of "Hardware Store"
- **Auto-creation**: If no match exists, an "Add new category" option appears. For hierarchical input, it shows "Create 'Paint' under 'Hardware Store'" and creates both if needed.

Hover over the **(i)** icon in the category input for a quick reminder of the `>` syntax.

---

## Categories

The Categories page manages your category hierarchy and connects bank categories to your own categories.

### Category tree

The top section shows all categories in a tree structure. Each category displays:
- Its **name** (double-click to rename inline — press Enter to save, Escape to cancel)
- A **type badge** — click to toggle between "income" and "expense"
- A **"Bank" badge** if it was auto-imported from a bank CSV
- A **Delete** button (only on categories with no children)

### Creating categories

Use the form at the top:
1. Enter a name
2. Choose a parent (or "Top-level" for a root category)
3. Choose the type: Expense or Income
4. Click **Add**

### Bank Category Mappings

The bottom section connects bank-assigned categories to your own categories. This is used by the Budget feature.

**Unmapped categories** are bank categories (from your CSV imports) that haven't been assigned to any of your categories yet. They appear in an amber banner.

For each bank category:
- If **mapped**: Shows which of your categories it maps to, with a "Remove" button
- If **unmapped**: Shows a dropdown to select one of your categories, with a "Map" button

Example: Map the bank category "Boodschappen" to your category "Groceries". Now all transactions with that bank category will count toward your Groceries budget.

---

## Budget

The Budget page lets you plan monthly spending and compare your plan against actual transactions.

### Setting up (first time)

Before the Budget page shows useful data, you need to:
1. **Create categories** on the Categories page (e.g., "Groceries", "Rent", "Salary") — mark each as income or expense
2. **Map bank categories** to your categories (on the Categories page, in the Bank Category Mappings section)
3. **Create a budget** for a month

### Navigating months

Use the left/right arrows next to the month name to browse between months.

### Creating a budget

If no budget exists for the selected month:
- Click **"Create Budget"** to start with a blank budget
- Or click **"Copy from [month]"** to duplicate the nearest previous month's budget and adjust from there

### Editing a budget

Click **"Edit Budget"** to enter edit mode:
- All your categories appear, split into Income and Expense sections
- Enter the budgeted amount for each category
- Categories with amount 0 are ignored
- Click **Save** to apply, or **Cancel** to discard changes

### Budget vs Actual view

Once a budget exists and bank categories are mapped, the page shows:

**Summary cards**: Budgeted Income, Actual Income, Budgeted Expenses, Actual Expenses, Net, and Savings Rate (as a percentage of income)

**Income table**: Each income category with budgeted amount, actual amount, difference, and a progress bar

**Expense table**: Each expense category with budgeted amount, actual amount, remaining amount, and a progress bar:
- **Green bar**: Under budget
- **Red bar**: Over budget (row also highlights red)

**Unmapped warning**: If there are transactions from bank categories that haven't been mapped to any of your categories, a warning appears at the bottom showing the total unmapped amount and a link to configure mappings.

### Deleting a budget

Click **"Delete"** next to "Edit Budget" to remove the budget for the current month. This doesn't affect your transactions.

---

## Typical Workflows

### Monthly routine

1. **Export** your latest transactions from ASN Bank (with category column)
2. **Import** the CSV on the Import page
3. Check the **Dashboard** to see your spending overview
4. Review the **Budget** page to see if you're on track
5. Optionally upload **receipts** for detailed line-item tracking

### Setting up budgeting for the first time

1. Go to **Categories** and create your budget categories (e.g., Groceries, Rent, Utilities, Salary, Freelance)
2. Set each category as "income" or "expense" using the type badge
3. Scroll down to **Bank Category Mappings** and map each bank category to one of your categories
4. Go to **Budget**, create a budget for the current month
5. Enter your expected income and spending limits per category
6. Next month, use **"Copy from previous"** and adjust as needed

### Detailed receipt tracking

1. Upload a receipt photo on the **Receipts** page
2. Review and correct the OCR output
3. If it wasn't auto-matched, link it to a transaction manually
4. On the transaction detail page, review and edit the **line items** extracted from the receipt
5. Categorize each line item (e.g., a supermarket receipt might have items tagged as "Dairy", "Vegetables", "Snacks")
6. The Dashboard's category drill-down will now show these subcategories

### Re-categorizing transactions

If a transaction has the wrong category:
1. Click on the transaction
2. Use the **category dropdown** to select the correct category
3. The change is saved immediately and reflected in the Dashboard and Budget views
