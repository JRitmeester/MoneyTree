# ASN Bank Sync Automation - Design

## Problem

Importing bank statements into MoneyTree requires manually logging into ASN Bank's online portal, exporting a CSV file, and uploading it through the MoneyTree import page. This is tedious and easy to forget.

## Solution

Automate the export step using Playwright browser automation. A "Sync from bank" button in the MoneyTree UI triggers a headless browser that logs into ASN Bank, navigates to the transaction export page, downloads the CSV, and feeds it into the existing import pipeline.

## Architecture

```
Frontend (Import page)
  ├── "Sync from bank" button
  ├── QR code display (when login required)
  └── Import results (same as CSV import)
        │
        ▼
Backend API
  ├── POST /api/bank-sync/start    → trigger sync
  ├── GET  /api/bank-sync/status   → session state + QR screenshot
  └── POST /api/bank-sync/stop     → close browser session
        │
        ▼
BankSyncService (Playwright singleton)
  ├── Persistent browser context (cookies saved to disk)
  ├── Login flow with QR code relay to frontend
  ├── Transaction export automation
  └── CSV download → parse_asn_csv() → existing import logic
```

## Sync Flow

### User Experience

1. Click "Sync from bank" on import page
2. If already logged in → sync starts immediately (~10 seconds)
3. If not logged in → QR code appears in the MoneyTree UI → scan with ASN app → sync proceeds automatically
4. Import results shown identically to manual CSV import (imported/skipped/updated counts, receipt matches)

### Date Range Strategy

- **Default**: From `MAX(datum)` in transactions table minus 1 day → today
- **First sync**: Maximum allowed range (up to 18 months)
- **Overlap handling**: The 1-day overlap ensures no gaps; existing `import_hash` deduplication skips already-imported transactions

### Browser Session Management

- Playwright persistent context saves cookies/local storage to `data/browser-state/`
- Session may survive across MoneyTree restarts (depends on ASN Bank's cookie policy)
- Optional periodic page refresh to prevent session timeout
- Session duration to be discovered empirically

## Key Design Decisions

1. **QR code relay over headed browser**: The browser runs headless. QR code is screenshot and served to the frontend via the status endpoint. No visible browser window needed.

2. **Reuses existing import pipeline**: Downloaded CSV fed directly into `parse_asn_csv()` and the same deduplication/import logic. Zero code duplication.

3. **Singleton service**: One browser instance per MoneyTree process. Avoids multiple concurrent sessions with the bank.

4. **No new database tables**: Last sync date derived from `MAX(datum)` on existing transactions table. No schema migration needed.

5. **Derive date range from data**: Rather than a fixed 30-day window, calculate from last transaction + 1 day overlap.

## API Endpoints

### POST /api/bank-sync/start

Triggers a bank sync. Returns immediately with a sync ID.

Response:
```json
{
  "sync_id": "uuid",
  "status": "starting"
}
```

### GET /api/bank-sync/status

Returns current sync state.

Response (when login needed):
```json
{
  "status": "awaiting_login",
  "qr_screenshot": "base64-encoded-png"
}
```

Response (when syncing):
```json
{
  "status": "syncing",
  "step": "downloading_transactions"
}
```

Response (when complete):
```json
{
  "status": "complete",
  "result": { /* same ImportResult as CSV import */ }
}
```

### POST /api/bank-sync/stop

Closes the browser session. Used to force re-login or clean up.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| QR not scanned within 2 min | Abort, report "Login timed out" |
| Session expired mid-sync | Detect redirect to login page, update status |
| Export page selectors changed | Fail with descriptive error about which selector broke |
| No new transactions | Report "No new transactions found" (not an error) |
| ASN returns zip file | Auto-extract CSV from zip before parsing |
| Playwright not installed | Graceful error with install instructions |

## File Changes

### New Files

```
backend/app/services/bank_sync.py    # BankSyncService (Playwright automation)
backend/app/routers/bank_sync.py     # API endpoints
```

### Modified Files

```
backend/app/main.py                  # Register bank_sync router
backend/requirements.txt             # Add playwright
frontend/src/routes/import/+page.svelte  # Add sync button + status UI
frontend/src/lib/api.ts              # Add bank sync API functions
```

### Unchanged

```
backend/app/services/csv_parser.py   # Reused as-is
backend/app/routers/transactions.py  # Import logic reused internally
backend/app/models.py                # No schema changes
```

## New Dependencies

- `playwright` - Browser automation library

## ASN Bank Portal Flow (to automate)

Based on research of mijn.asnbank.nl:

1. Navigate to mijn.asnbank.nl
2. Login page shows QR code → user scans with ASN app
3. After login, navigate to account overview
4. Click "transacties downloaden" / transaction export
5. Set date range (since last sync - 1 day)
6. Select CSV format
7. Click download
8. Handle potential zip extraction
9. Feed CSV content to parse_asn_csv()

Note: Exact selectors will need to be discovered during implementation by inspecting the live site.

## Risks

- **Site changes**: ASN Bank may update their portal, breaking selectors. Mitigation: clear error messages pointing to what broke, selectors defined as constants for easy updates.
- **2FA changes**: If ASN changes their login flow (e.g., moves away from QR codes), the login automation needs updating.
- **Rate limiting**: Unlikely for normal usage, but avoid hammering the site.
- **Terms of service**: Browser automation of banking sites may violate ToS. This is a personal tool for personal use.
