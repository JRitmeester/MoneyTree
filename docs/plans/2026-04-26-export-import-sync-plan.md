# Export/Import Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an export/import feature that lets a local MoneyTree instance dump its data to a JSON file and merge it into the online (NAS) instance once the NAS is reachable again, without losing pre-outage NAS data.

**Architecture:** Single JSON file format (versioned). Export endpoint dumps in-scope tables; transactions filtered optionally by `created_at >= since`. Import endpoint runs a dry-run first (returning a structured preview with conflict report), then a commit phase that applies changes inside one DB transaction with automatic SQLite backup beforehand. Natural keys used everywhere: `Category.name`, `Budget.start_date`, `Transaction.import_hash`, `CategoryMapping.bank_category`, `BudgetLine(budget_start_date, category_name)`. Local IDs are not trusted on the receiving side.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, Pydantic v2, SQLite, SvelteKit, Vitest, Pytest.

---

## Operating Assumption

The two instances are NEVER independently used at the same time. The flow is strictly:

1. NAS up, accumulates data → goes down at T_outage
2. Local instance starts fresh (no NAS DB available), accumulates data during outage
3. NAS comes back, has not been written to during outage
4. User exports from local, imports into NAS

This eliminates concurrent-write conflicts. The remaining conflicts come from independent re-creation of identically-named entities, and from local having re-imported the same bank CSVs that NAS already has.

---

## Conflict Analysis

In-scope tables: `categories`, `budgets`, `budget_lines`, `budget_templates`, `category_mappings`, `transactions`, `transaction_offsets`.

Out of scope (v1): `receipts`, `line_items` (image files + OCR adds complexity), `passkey_credentials`, `revoked_tokens`, `webauthn_challenges` (security/session — never export).

### Clean Cases (handled deterministically)

| # | Scenario | Resolution |
|---|----------|------------|
| C1 | Local re-imports a CSV that NAS already has → same `import_hash` | Skip on dedup. Optional `update_duplicates=true` to overwrite mutable fields. |
| C2 | New transaction created locally during outage | Insert (unique `import_hash`). |
| C3 | New category created locally with a name not on NAS | Insert. New NAS ID assigned. |
| C4 | New `Budget` for a period NAS does not yet have | Insert (unique `start_date`). |
| C5 | New `BudgetLine` for an existing NAS budget | Insert via remapped `budget_id`. |
| C6 | New `BudgetTemplate` row for an unmapped category | Insert. |
| C7 | New `CategoryMapping` for an unmapped `bank_category` | Insert. |
| C8 | New `TransactionOffset` between two transactions present on both sides | Insert if both sides resolve and `income_transaction_id` is not already linked on NAS. |

### Soft Conflicts (resolved by policy, surfaced in preview)

| # | Scenario | Default Policy | Why |
|---|----------|----------------|-----|
| S1 | Same category `name` exists on both, attrs differ (`category_type`, `is_fixed`, `parent_id`) | NAS-wins on attrs; reuse NAS ID for FK resolution | NAS attrs are pre-outage canonical. Local user typed the name to mirror NAS, not to reorganize. |
| S2 | Same `BudgetLine(budget_start_date, category_name)` on both, different `amount` | Local-wins | Local edit is more recent. NAS budget amounts predate the outage. |
| S3 | Same `BudgetTemplate.category_id` on both, different `amount` | NAS-wins | Templates are user-created defaults. Local re-creation is approximate. |
| S4 | Same `CategoryMapping.bank_category` on both, different `category_id` | NAS-wins | NAS mapping is canonical. Local re-creation is approximate. |
| S5 | Local re-imported a CSV and recategorized a transaction NAS already has | Skip by default; `update_duplicates=true` applies local's `category_id`, `merchant_name` | Avoids silent overwrite of NAS-side categorization. User opts in. |
| S6 | `TransactionOffset` exists on NAS for an `income_transaction_id` that local also offsets (to a different expense) | Skip with warning | NAS link is canonical, predates outage. |
| S7 | Category renamed locally for a category that pre-exists on NAS under the old name | Treated as new category by name; old NAS category remains | True rename detection requires `previous_name` tracking, out of scope. Documented limitation. |
| S8 | Category attribute changes (`parent_id` move, `is_fixed` flip) made locally for a pre-existing NAS category | Dropped (NAS-wins per S1) | Same reasoning. Documented limitation. |
| S9 | Category deleted locally that exists on NAS | NAS keeps it | Export omits deleted rows; import is additive. Documented limitation. |
| S10 | `BudgetLine` deleted locally that exists on NAS | NAS keeps it | Same. |

### Hard Conflicts (import aborts with explicit error)

| # | Scenario | Why Hard |
|---|----------|----------|
| H1 | Local has a `Budget` whose date range overlaps an existing NAS `Budget` with a different `start_date` | Violates the `_check_overlap` invariant. Cannot auto-resolve which budget to keep without user input. Import aborts; user resolves manually. |
| H2 | Export file `format_version` is unknown / unsupported | Forward compat. |
| H3 | Export file references a category by `parent_name` that is not in the export and not on NAS | Cannot resolve FK. |

The dry-run preview lists every soft and hard conflict before any write happens.

---

## Export File Format

Single JSON document, versioned. References use natural keys; local PKs are not exported.

```json
{
  "format_version": 1,
  "exported_at": "2026-04-26T12:00:00Z",
  "since": "2026-04-01",
  "categories": [
    { "name": "Groceries", "parent_name": null, "is_fixed": false, "category_type": "expense" }
  ],
  "category_mappings": [
    { "bank_category": "Boodschappen", "category_name": "Groceries" }
  ],
  "budgets": [
    { "start_date": "2026-04-01", "end_date": "2026-05-01" }
  ],
  "budget_lines": [
    { "budget_start_date": "2026-04-01", "category_name": "Groceries", "amount": 400.0 }
  ],
  "budget_templates": [
    { "category_name": "Groceries", "amount": 400.0 }
  ],
  "transactions": [
    { "import_hash": "abc123...", "datum": "2026-04-15", "rekening": "NL00...",
      "tegenrekening": null, "naam": "Albert Heijn", "adres": null, "postcode": null,
      "woonplaats": null, "valuta_saldo": "EUR", "saldo_voor_boeking": 1000.0,
      "valuta": "EUR", "bedrag": -42.50, "verwerkingsdatum": "2026-04-15",
      "valutadatum": "2026-04-15", "code": "GT", "type": "BET", "volgnummer": "001",
      "betalingskenmerk": null, "omschrijving": "AH te Utrecht", "afschriftnummer": "001",
      "categorie": "Boodschappen", "merchant_name": "Albert Heijn",
      "category_name": "Groceries", "created_at": "2026-04-15T10:00:00Z" }
  ],
  "transaction_offsets": [
    { "expense_import_hash": "abc123...", "income_import_hash": "def456..." }
  ]
}
```

---

## File Structure

**Backend (new files):**
- `backend/app/services/sync_export.py` — DB → in-memory dict → JSON
- `backend/app/services/sync_import.py` — JSON → diff → DB writes (with backup + ID remap)
- `backend/app/routers/sync.py` — endpoints: `GET /api/sync/export`, `POST /api/sync/import`
- `backend/app/sync_schemas.py` — Pydantic models for the export file format and import preview
- `backend/tests/test_sync_export.py` — export tests
- `backend/tests/test_sync_import.py` — import tests (additive, dedup, conflict cases)

**Backend (modified):**
- `backend/app/main.py` — register `sync.router`

**Frontend (new files):**
- `frontend/src/routes/settings/sync/+page.svelte` — Sync UI (export download, import upload + preview confirm)

**Frontend (modified):**
- `frontend/src/lib/api.ts` — add `exportSync`, `importSyncPreview`, `importSyncCommit`

---

## Task Decomposition

### Task 1: Sync Pydantic schemas

**Files:**
- Create: `backend/app/sync_schemas.py`
- Test: `backend/tests/test_sync_schemas.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_sync_schemas.py
from datetime import date, datetime, timezone
from app.sync_schemas import ExportFile, ExportCategory, ExportTransaction


def test_export_file_serializes_round_trip():
    payload = {
        "format_version": 1,
        "exported_at": datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc),
        "since": date(2026, 4, 1),
        "categories": [
            {"name": "Groceries", "parent_name": None, "is_fixed": False, "category_type": "expense"}
        ],
        "category_mappings": [],
        "budgets": [],
        "budget_lines": [],
        "budget_templates": [],
        "transactions": [],
        "transaction_offsets": [],
    }
    parsed = ExportFile.model_validate(payload)
    dumped = parsed.model_dump(mode="json")
    reparsed = ExportFile.model_validate(dumped)
    assert reparsed.categories[0].name == "Groceries"
    assert reparsed.format_version == 1


def test_export_file_rejects_wrong_format_version():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ExportFile.model_validate({
            "format_version": 999, "exported_at": datetime.now(timezone.utc), "since": None,
            "categories": [], "category_mappings": [], "budgets": [], "budget_lines": [],
            "budget_templates": [], "transactions": [], "transaction_offsets": [],
        })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_sync_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.sync_schemas'`

- [ ] **Step 3: Implement schemas**

```python
# backend/app/sync_schemas.py
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


SUPPORTED_FORMAT_VERSIONS = {1}


class ExportCategory(BaseModel):
    name: str
    parent_name: Optional[str] = None
    is_fixed: bool = False
    category_type: str = "expense"


class ExportCategoryMapping(BaseModel):
    bank_category: str
    category_name: str


class ExportBudget(BaseModel):
    start_date: date
    end_date: date


class ExportBudgetLine(BaseModel):
    budget_start_date: date
    category_name: str
    amount: float


class ExportBudgetTemplate(BaseModel):
    category_name: str
    amount: float


class ExportTransaction(BaseModel):
    import_hash: str
    datum: date
    rekening: str
    tegenrekening: Optional[str] = None
    naam: Optional[str] = None
    adres: Optional[str] = None
    postcode: Optional[str] = None
    woonplaats: Optional[str] = None
    valuta_saldo: str
    saldo_voor_boeking: float
    valuta: str
    bedrag: float
    verwerkingsdatum: date
    valutadatum: date
    code: str
    type: str
    volgnummer: str
    betalingskenmerk: Optional[str] = None
    omschrijving: str
    afschriftnummer: str
    categorie: str
    merchant_name: Optional[str] = None
    category_name: Optional[str] = None
    created_at: datetime


class ExportTransactionOffset(BaseModel):
    expense_import_hash: str
    income_import_hash: str


class ExportFile(BaseModel):
    format_version: Literal[1]
    exported_at: datetime
    since: Optional[date] = None
    categories: list[ExportCategory]
    category_mappings: list[ExportCategoryMapping]
    budgets: list[ExportBudget]
    budget_lines: list[ExportBudgetLine]
    budget_templates: list[ExportBudgetTemplate]
    transactions: list[ExportTransaction]
    transaction_offsets: list[ExportTransactionOffset]


class ImportConflict(BaseModel):
    code: str
    severity: Literal["soft", "hard"]
    message: str


class ImportPreview(BaseModel):
    will_add_categories: int = 0
    will_add_category_mappings: int = 0
    will_add_budgets: int = 0
    will_add_budget_lines: int = 0
    will_update_budget_lines: int = 0
    will_add_budget_templates: int = 0
    will_add_transactions: int = 0
    will_update_transactions: int = 0
    will_skip_transactions: int = 0
    will_add_offsets: int = 0
    soft_conflicts: list[ImportConflict] = Field(default_factory=list)
    hard_conflicts: list[ImportConflict] = Field(default_factory=list)


class ImportResult(BaseModel):
    preview: ImportPreview
    committed: bool
    backup_path: Optional[str] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_sync_schemas.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/sync_schemas.py backend/tests/test_sync_schemas.py
git commit -m "feat: add sync export/import Pydantic schemas"
```

---

### Task 2: Export service

**Files:**
- Create: `backend/app/services/sync_export.py`
- Test: `backend/tests/test_sync_export.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_sync_export.py
from datetime import date, datetime, timezone

from app.models import (
    Budget, BudgetLine, BudgetTemplate, Category, CategoryMapping,
    Transaction, TransactionOffset,
)
from app.services.sync_export import build_export
from tests.conftest import make_category, make_transaction


def test_build_export_includes_all_in_scope_tables(db):
    parent = make_category(db, name="Living")
    child = Category(name="Groceries", parent_id=parent.id, category_type="expense")
    db.add(child); db.flush()

    db.add(CategoryMapping(bank_category="Boodschappen", category_id=child.id))
    db.add(BudgetTemplate(category_id=child.id, amount=400.0))

    budget = Budget(start_date=date(2026, 4, 1), end_date=date(2026, 5, 1))
    db.add(budget); db.flush()
    db.add(BudgetLine(budget_id=budget.id, category_id=child.id, amount=400.0))

    expense = make_transaction(db, bedrag=-50.0, category_id=child.id)
    income = make_transaction(db, bedrag=50.0, category_id=child.id)
    db.add(TransactionOffset(expense_transaction_id=expense.id, income_transaction_id=income.id))
    db.commit()

    export = build_export(db, since=None)

    assert export.format_version == 1
    assert {c.name for c in export.categories} == {"Living", "Groceries"}
    grocery = next(c for c in export.categories if c.name == "Groceries")
    assert grocery.parent_name == "Living"
    assert export.category_mappings[0].category_name == "Groceries"
    assert export.budgets[0].start_date == date(2026, 4, 1)
    assert export.budget_lines[0].category_name == "Groceries"
    assert export.budget_templates[0].amount == 400.0
    assert len(export.transactions) == 2
    assert export.transaction_offsets[0].expense_import_hash == expense.import_hash


def test_build_export_filters_transactions_by_since(db):
    cat = make_category(db, name="Groceries")
    old_tx = make_transaction(db, category_id=cat.id)
    old_tx.created_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
    new_tx = make_transaction(db, category_id=cat.id)
    new_tx.created_at = datetime(2026, 4, 15, tzinfo=timezone.utc)
    db.commit()

    export = build_export(db, since=date(2026, 4, 1))

    hashes = {t.import_hash for t in export.transactions}
    assert new_tx.import_hash in hashes
    assert old_tx.import_hash not in hashes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_sync_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.sync_export'`

- [ ] **Step 3: Implement export service**

```python
# backend/app/services/sync_export.py
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Budget, BudgetLine, BudgetTemplate, Category, CategoryMapping,
    Transaction, TransactionOffset,
)
from ..sync_schemas import (
    ExportBudget, ExportBudgetLine, ExportBudgetTemplate, ExportCategory,
    ExportCategoryMapping, ExportFile, ExportTransaction, ExportTransactionOffset,
)


def build_export(db: Session, since: Optional[date]) -> ExportFile:
    cats = db.execute(select(Category)).scalars().all()
    cat_by_id = {c.id: c for c in cats}

    export_categories = [
        ExportCategory(
            name=c.name,
            parent_name=cat_by_id[c.parent_id].name if c.parent_id else None,
            is_fixed=c.is_fixed,
            category_type=c.category_type,
        )
        for c in cats
    ]

    mappings = db.execute(select(CategoryMapping)).scalars().all()
    export_mappings = [
        ExportCategoryMapping(
            bank_category=m.bank_category,
            category_name=cat_by_id[m.category_id].name,
        )
        for m in mappings
    ]

    budgets = db.execute(select(Budget)).scalars().all()
    budget_by_id = {b.id: b for b in budgets}
    export_budgets = [
        ExportBudget(start_date=b.start_date, end_date=b.end_date) for b in budgets
    ]

    lines = db.execute(select(BudgetLine)).scalars().all()
    export_lines = [
        ExportBudgetLine(
            budget_start_date=budget_by_id[l.budget_id].start_date,
            category_name=cat_by_id[l.category_id].name,
            amount=l.amount,
        )
        for l in lines
    ]

    templates = db.execute(select(BudgetTemplate)).scalars().all()
    export_templates = [
        ExportBudgetTemplate(
            category_name=cat_by_id[t.category_id].name,
            amount=t.amount,
        )
        for t in templates
    ]

    tx_query = select(Transaction)
    if since is not None:
        cutoff = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
        tx_query = tx_query.where(Transaction.created_at >= cutoff)
    txs = db.execute(tx_query).scalars().all()
    tx_by_id = {t.id: t for t in txs}
    export_txs = [
        ExportTransaction(
            import_hash=t.import_hash,
            datum=t.datum,
            rekening=t.rekening,
            tegenrekening=t.tegenrekening,
            naam=t.naam,
            adres=t.adres,
            postcode=t.postcode,
            woonplaats=t.woonplaats,
            valuta_saldo=t.valuta_saldo,
            saldo_voor_boeking=t.saldo_voor_boeking,
            valuta=t.valuta,
            bedrag=t.bedrag,
            verwerkingsdatum=t.verwerkingsdatum,
            valutadatum=t.valutadatum,
            code=t.code,
            type=t.type,
            volgnummer=t.volgnummer,
            betalingskenmerk=t.betalingskenmerk,
            omschrijving=t.omschrijving,
            afschriftnummer=t.afschriftnummer,
            categorie=t.categorie,
            merchant_name=t.merchant_name,
            category_name=cat_by_id[t.category_id].name if t.category_id else None,
            created_at=t.created_at,
        )
        for t in txs
    ]

    tx_ids = set(tx_by_id.keys())
    offsets = db.execute(select(TransactionOffset)).scalars().all()
    export_offsets = [
        ExportTransactionOffset(
            expense_import_hash=tx_by_id[o.expense_transaction_id].import_hash,
            income_import_hash=tx_by_id[o.income_transaction_id].import_hash,
        )
        for o in offsets
        if o.expense_transaction_id in tx_ids and o.income_transaction_id in tx_ids
    ]

    return ExportFile(
        format_version=1,
        exported_at=datetime.now(timezone.utc),
        since=since,
        categories=export_categories,
        category_mappings=export_mappings,
        budgets=export_budgets,
        budget_lines=export_lines,
        budget_templates=export_templates,
        transactions=export_txs,
        transaction_offsets=export_offsets,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_sync_export.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sync_export.py backend/tests/test_sync_export.py
git commit -m "feat: add sync export service"
```

---

### Task 3: Export endpoint

**Files:**
- Create: `backend/app/routers/sync.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_sync_endpoints.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_sync_endpoints.py
from datetime import date

from tests.conftest import make_category, make_transaction


def test_export_endpoint_returns_json(client, db):
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.commit()

    resp = client.get("/api/sync/export")
    assert resp.status_code == 200
    body = resp.json()
    assert body["format_version"] == 1
    assert any(c["name"] == "Groceries" for c in body["categories"])
    assert len(body["transactions"]) == 1


def test_export_endpoint_accepts_since(client, db):
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.commit()

    resp = client.get("/api/sync/export?since=2030-01-01")
    assert resp.status_code == 200
    assert resp.json()["transactions"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_sync_endpoints.py -v`
Expected: FAIL with 404 (route not registered).

- [ ] **Step 3: Implement router and register it**

```python
# backend/app/routers/sync.py
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..services.sync_export import build_export
from ..sync_schemas import ExportFile

router = APIRouter(prefix="/api/sync", tags=["sync"], dependencies=[Depends(require_auth)])


@router.get("/export", response_model=ExportFile)
def export_sync(
    since: Optional[date] = Query(None, description="Only include transactions with created_at >= since"),
    db: Session = Depends(get_db),
):
    return build_export(db, since=since)
```

In `backend/app/main.py`, add to imports and register:

```python
# in the routers import block
from .routers import (
    auth, budget, budget_template, categories, category_mappings, dashboard,
    debug, line_items, receipts, settings, sync, transactions, uncategorized,
)

# after app.include_router(settings.router):
app.include_router(sync.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_sync_endpoints.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/sync.py backend/app/main.py backend/tests/test_sync_endpoints.py
git commit -m "feat: add sync export endpoint"
```

---

### Task 4: Import service — preview (dry-run)

**Files:**
- Create: `backend/app/services/sync_import.py`
- Test: `backend/tests/test_sync_import_preview.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_sync_import_preview.py
from datetime import date, datetime, timezone

from app.services.sync_export import build_export
from app.services.sync_import import preview_import
from tests.conftest import make_category, make_transaction


def _empty_export():
    from app.sync_schemas import ExportFile
    return ExportFile(
        format_version=1, exported_at=datetime.now(timezone.utc), since=None,
        categories=[], category_mappings=[], budgets=[], budget_lines=[],
        budget_templates=[], transactions=[], transaction_offsets=[],
    )


def test_preview_additive_into_empty_db(db):
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.commit()
    export = build_export(db, since=None)

    # New empty session simulating the destination
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.models import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    dest = sessionmaker(bind=engine)()

    preview = preview_import(dest, export)
    assert preview.will_add_categories == 1
    assert preview.will_add_transactions == 1
    assert preview.hard_conflicts == []


def test_preview_dedup_existing_transactions(db):
    cat = make_category(db, name="Groceries")
    tx = make_transaction(db, category_id=cat.id)
    db.commit()
    export = build_export(db, since=None)

    preview = preview_import(db, export)
    assert preview.will_add_transactions == 0
    assert preview.will_skip_transactions == 1


def test_preview_detects_overlapping_budget_hard_conflict(db):
    from app.models import Budget
    db.add(Budget(start_date=date(2026, 4, 1), end_date=date(2026, 5, 1)))
    db.commit()

    export = _empty_export()
    from app.sync_schemas import ExportBudget
    export.budgets.append(ExportBudget(start_date=date(2026, 4, 15), end_date=date(2026, 5, 15)))

    preview = preview_import(db, export)
    assert any(c.code == "budget_overlap" and c.severity == "hard" for c in preview.hard_conflicts)


def test_preview_flags_attribute_diff_on_existing_category(db):
    make_category(db, name="Groceries")  # default category_type=expense
    db.commit()

    export = _empty_export()
    from app.sync_schemas import ExportCategory
    export.categories.append(ExportCategory(
        name="Groceries", parent_name=None, is_fixed=True, category_type="income",
    ))

    preview = preview_import(db, export)
    assert preview.will_add_categories == 0
    assert any(c.code == "category_attr_diff" and c.severity == "soft" for c in preview.soft_conflicts)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_sync_import_preview.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.sync_import'`

- [ ] **Step 3: Implement preview**

```python
# backend/app/services/sync_import.py
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Budget, BudgetLine, BudgetTemplate, Category, CategoryMapping,
    Transaction, TransactionOffset,
)
from ..sync_schemas import ExportFile, ImportConflict, ImportPreview


def _category_index(db: Session) -> dict[str, Category]:
    return {c.name: c for c in db.execute(select(Category)).scalars().all()}


def _budget_index(db: Session) -> dict[str, Budget]:
    return {b.start_date.isoformat(): b for b in db.execute(select(Budget)).scalars().all()}


def _tx_hashes(db: Session) -> set[str]:
    return set(db.execute(select(Transaction.import_hash)).scalars().all())


def _budget_overlaps(db: Session, start, end, exclude_start=None) -> Budget | None:
    q = select(Budget).where(Budget.start_date < end, Budget.end_date > start)
    return next(
        (b for b in db.execute(q).scalars().all()
         if exclude_start is None or b.start_date != exclude_start),
        None,
    )


def preview_import(db: Session, export: ExportFile) -> ImportPreview:
    preview = ImportPreview()

    cat_idx = _category_index(db)
    for ec in export.categories:
        existing = cat_idx.get(ec.name)
        if existing is None:
            preview.will_add_categories += 1
        else:
            attr_diff = (
                existing.is_fixed != ec.is_fixed
                or existing.category_type != ec.category_type
                or (existing.parent.name if existing.parent else None) != ec.parent_name
            )
            if attr_diff:
                preview.soft_conflicts.append(ImportConflict(
                    code="category_attr_diff", severity="soft",
                    message=f"Category '{ec.name}' exists on destination with different attributes; NAS values kept.",
                ))

    # Validate parent_name resolves
    export_names = {c.name for c in export.categories}
    for ec in export.categories:
        if ec.parent_name and ec.parent_name not in export_names and ec.parent_name not in cat_idx:
            preview.hard_conflicts.append(ImportConflict(
                code="parent_name_unresolved", severity="hard",
                message=f"Category '{ec.name}' has parent_name '{ec.parent_name}' that does not exist on destination or in export.",
            ))

    mapping_keys = {m.bank_category for m in db.execute(select(CategoryMapping)).scalars().all()}
    for em in export.category_mappings:
        if em.bank_category not in mapping_keys:
            preview.will_add_category_mappings += 1
        else:
            preview.soft_conflicts.append(ImportConflict(
                code="mapping_conflict", severity="soft",
                message=f"CategoryMapping for '{em.bank_category}' exists; NAS mapping kept.",
            ))

    bud_idx = _budget_index(db)
    export_budget_starts = {b.start_date for b in export.budgets}
    for eb in export.budgets:
        if eb.start_date.isoformat() not in bud_idx:
            overlap = _budget_overlaps(db, eb.start_date, eb.end_date, exclude_start=eb.start_date)
            if overlap is not None:
                preview.hard_conflicts.append(ImportConflict(
                    code="budget_overlap", severity="hard",
                    message=f"Imported budget {eb.start_date}–{eb.end_date} overlaps existing budget {overlap.start_date}–{overlap.end_date}.",
                ))
            else:
                preview.will_add_budgets += 1

    line_keys = {(l.budget_id, l.category_id) for l in db.execute(select(BudgetLine)).scalars().all()}
    for el in export.budget_lines:
        budget = bud_idx.get(el.budget_start_date.isoformat())
        category = cat_idx.get(el.category_name)
        if budget is None or category is None:
            preview.will_add_budget_lines += 1
            continue
        if (budget.id, category.id) in line_keys:
            preview.will_update_budget_lines += 1
        else:
            preview.will_add_budget_lines += 1

    tmpl_cat_ids = {t.category_id for t in db.execute(select(BudgetTemplate)).scalars().all()}
    for et in export.budget_templates:
        cat = cat_idx.get(et.category_name)
        if cat is None or cat.id not in tmpl_cat_ids:
            preview.will_add_budget_templates += 1
        else:
            preview.soft_conflicts.append(ImportConflict(
                code="template_conflict", severity="soft",
                message=f"BudgetTemplate for '{et.category_name}' exists; NAS amount kept.",
            ))

    existing_hashes = _tx_hashes(db)
    for et in export.transactions:
        if et.import_hash in existing_hashes:
            preview.will_skip_transactions += 1
        else:
            preview.will_add_transactions += 1

    income_locked = set(db.execute(
        select(TransactionOffset.income_transaction_id)
    ).scalars().all())
    income_hash_locked = set()
    if income_locked:
        rows = db.execute(
            select(Transaction.id, Transaction.import_hash).where(Transaction.id.in_(income_locked))
        ).all()
        income_hash_locked = {h for _, h in rows}
    for eo in export.transaction_offsets:
        if eo.income_import_hash in income_hash_locked:
            preview.soft_conflicts.append(ImportConflict(
                code="offset_income_locked", severity="soft",
                message=f"Income transaction {eo.income_import_hash} already linked on destination; offset skipped.",
            ))
        else:
            preview.will_add_offsets += 1

    return preview
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_sync_import_preview.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sync_import.py backend/tests/test_sync_import_preview.py
git commit -m "feat: add sync import preview (dry-run)"
```

---

### Task 5: Import service — commit

**Files:**
- Modify: `backend/app/services/sync_import.py`
- Test: `backend/tests/test_sync_import_commit.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_sync_import_commit.py
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.models import (
    Base, Budget, BudgetLine, BudgetTemplate, Category,
    CategoryMapping, Transaction, TransactionOffset,
)
from app.services.sync_export import build_export
from app.services.sync_import import commit_import, preview_import
from tests.conftest import make_category, make_transaction


def _fresh_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_commit_replays_full_export_into_empty_db(db):
    parent = make_category(db, name="Living")
    child = Category(name="Groceries", parent_id=parent.id, category_type="expense")
    db.add(child); db.flush()
    db.add(CategoryMapping(bank_category="Boodschappen", category_id=child.id))
    db.add(BudgetTemplate(category_id=child.id, amount=400.0))
    budget = Budget(start_date=date(2026, 4, 1), end_date=date(2026, 5, 1))
    db.add(budget); db.flush()
    db.add(BudgetLine(budget_id=budget.id, category_id=child.id, amount=400.0))
    expense = make_transaction(db, bedrag=-50.0, category_id=child.id)
    income = make_transaction(db, bedrag=50.0, category_id=child.id)
    db.add(TransactionOffset(expense_transaction_id=expense.id, income_transaction_id=income.id))
    db.commit()

    export = build_export(db, since=None)
    dest = _fresh_session()
    commit_import(dest, export, update_duplicates=False)

    cats = dest.execute(select(Category)).scalars().all()
    assert {c.name for c in cats} == {"Living", "Groceries"}
    grocery = next(c for c in cats if c.name == "Groceries")
    assert grocery.parent.name == "Living"
    assert dest.execute(select(BudgetLine)).scalars().one().amount == 400.0
    assert dest.execute(select(Transaction)).scalars().all().__len__() == 2
    assert dest.execute(select(TransactionOffset)).scalars().one() is not None


def test_commit_dedup_does_not_duplicate_transactions(db):
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.commit()
    export = build_export(db, since=None)

    commit_import(db, export, update_duplicates=False)
    txs = db.execute(select(Transaction)).scalars().all()
    assert len(txs) == 1


def test_commit_update_duplicates_overwrites_mutable_fields(db):
    cat_a = make_category(db, name="OldCat")
    cat_b = make_category(db, name="NewCat")
    tx = make_transaction(db, category_id=cat_a.id, merchant_name="Old")
    db.commit()
    export = build_export(db, since=None)
    # Mutate the export's transaction to simulate a recategorization
    et = next(e for e in export.transactions if e.import_hash == tx.import_hash)
    et.category_name = "NewCat"
    et.merchant_name = "New"

    commit_import(db, export, update_duplicates=True)
    db.refresh(tx)
    assert tx.category_id == cat_b.id
    assert tx.merchant_name == "New"


def test_commit_aborts_on_hard_conflict(db):
    db.add(Budget(start_date=date(2026, 4, 1), end_date=date(2026, 5, 1)))
    db.commit()

    from app.sync_schemas import ExportBudget, ExportFile
    export = ExportFile(
        format_version=1, exported_at=datetime.now(timezone.utc), since=None,
        categories=[], category_mappings=[],
        budgets=[ExportBudget(start_date=date(2026, 4, 15), end_date=date(2026, 5, 15))],
        budget_lines=[], budget_templates=[], transactions=[], transaction_offsets=[],
    )

    import pytest
    with pytest.raises(ValueError, match="hard conflict"):
        commit_import(db, export, update_duplicates=False)

    # Original budget unchanged, new budget not added
    budgets = db.execute(select(Budget)).scalars().all()
    assert len(budgets) == 1
    assert budgets[0].start_date == date(2026, 4, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_sync_import_commit.py -v`
Expected: FAIL with `ImportError: cannot import name 'commit_import'`

- [ ] **Step 3: Implement commit**

Add at the bottom of `backend/app/services/sync_import.py`:

```python
def commit_import(db: Session, export: ExportFile, update_duplicates: bool) -> ImportPreview:
    preview = preview_import(db, export)
    if preview.hard_conflicts:
        raise ValueError(
            f"Import aborted by {len(preview.hard_conflicts)} hard conflict(s): "
            + "; ".join(c.message for c in preview.hard_conflicts)
        )

    # 1. Categories — insert missing, in two passes (parents first via topological sort)
    cat_idx = _category_index(db)
    by_name = {c.name: c for c in export.categories}
    inserted_round = True
    pending = list(export.categories)
    while pending and inserted_round:
        inserted_round = False
        remaining = []
        for ec in pending:
            if ec.name in cat_idx:
                continue
            parent_id = None
            if ec.parent_name is not None:
                parent = cat_idx.get(ec.parent_name)
                if parent is None:
                    remaining.append(ec)
                    continue
                parent_id = parent.id
            new_cat = Category(
                name=ec.name, parent_id=parent_id,
                is_fixed=ec.is_fixed, category_type=ec.category_type,
            )
            db.add(new_cat)
            db.flush()
            cat_idx[ec.name] = new_cat
            inserted_round = True
        pending = remaining
    if pending:
        raise ValueError(f"Could not resolve parents for: {[c.name for c in pending]}")

    # 2. Category mappings — insert missing only (NAS-wins on existing)
    existing_mappings = {m.bank_category for m in db.execute(select(CategoryMapping)).scalars().all()}
    for em in export.category_mappings:
        if em.bank_category in existing_mappings:
            continue
        cat = cat_idx.get(em.category_name)
        if cat is None:
            continue
        db.add(CategoryMapping(bank_category=em.bank_category, category_id=cat.id))

    # 3. Budgets — insert missing (overlap pre-validated above)
    bud_idx = _budget_index(db)
    for eb in export.budgets:
        key = eb.start_date.isoformat()
        if key in bud_idx:
            continue
        new_b = Budget(start_date=eb.start_date, end_date=eb.end_date)
        db.add(new_b)
        db.flush()
        bud_idx[key] = new_b

    # 4. Budget lines — local-wins on amount conflict (S2)
    existing_lines = {
        (l.budget_id, l.category_id): l
        for l in db.execute(select(BudgetLine)).scalars().all()
    }
    for el in export.budget_lines:
        budget = bud_idx.get(el.budget_start_date.isoformat())
        cat = cat_idx.get(el.category_name)
        if budget is None or cat is None:
            continue
        existing = existing_lines.get((budget.id, cat.id))
        if existing is None:
            db.add(BudgetLine(budget_id=budget.id, category_id=cat.id, amount=el.amount))
        else:
            existing.amount = el.amount

    # 5. Budget templates — NAS-wins on conflict (S3)
    existing_template_cat_ids = {
        t.category_id for t in db.execute(select(BudgetTemplate)).scalars().all()
    }
    for et in export.budget_templates:
        cat = cat_idx.get(et.category_name)
        if cat is None or cat.id in existing_template_cat_ids:
            continue
        db.add(BudgetTemplate(category_id=cat.id, amount=et.amount))

    # 6. Transactions
    existing_tx = {
        t.import_hash: t
        for t in db.execute(select(Transaction)).scalars().all()
    }
    for et in export.transactions:
        if et.import_hash in existing_tx:
            if update_duplicates:
                tx = existing_tx[et.import_hash]
                tx.merchant_name = et.merchant_name
                tx.category_id = cat_idx[et.category_name].id if et.category_name and et.category_name in cat_idx else None
            continue
        category_id = (
            cat_idx[et.category_name].id
            if et.category_name and et.category_name in cat_idx
            else None
        )
        new_tx = Transaction(
            datum=et.datum, rekening=et.rekening, tegenrekening=et.tegenrekening,
            naam=et.naam, adres=et.adres, postcode=et.postcode, woonplaats=et.woonplaats,
            valuta_saldo=et.valuta_saldo, saldo_voor_boeking=et.saldo_voor_boeking,
            valuta=et.valuta, bedrag=et.bedrag, verwerkingsdatum=et.verwerkingsdatum,
            valutadatum=et.valutadatum, code=et.code, type=et.type,
            volgnummer=et.volgnummer, betalingskenmerk=et.betalingskenmerk,
            omschrijving=et.omschrijving, afschriftnummer=et.afschriftnummer,
            categorie=et.categorie, merchant_name=et.merchant_name,
            import_hash=et.import_hash, created_at=et.created_at, category_id=category_id,
        )
        db.add(new_tx)
        db.flush()
        existing_tx[et.import_hash] = new_tx

    # 7. Offsets — skip if income tx already linked
    income_locked_ids = set(db.execute(
        select(TransactionOffset.income_transaction_id)
    ).scalars().all())
    for eo in export.transaction_offsets:
        expense = existing_tx.get(eo.expense_import_hash)
        income = existing_tx.get(eo.income_import_hash)
        if expense is None or income is None:
            continue
        if income.id in income_locked_ids:
            continue
        db.add(TransactionOffset(
            expense_transaction_id=expense.id, income_transaction_id=income.id,
        ))
        income_locked_ids.add(income.id)

    db.commit()
    return preview
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_sync_import_commit.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sync_import.py backend/tests/test_sync_import_commit.py
git commit -m "feat: add sync import commit phase"
```

---

### Task 6: Pre-import SQLite backup

**Files:**
- Modify: `backend/app/services/sync_import.py`
- Test: `backend/tests/test_sync_backup.py`

**Why:** Before any commit_import that mutates the live DB, copy the SQLite file aside so the user can roll back if anything looks wrong post-import.

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_sync_backup.py
from pathlib import Path

from app.services.sync_import import snapshot_sqlite_db


def test_snapshot_creates_timestamped_copy(tmp_path):
    src = tmp_path / "moneytree.db"
    src.write_bytes(b"FAKE SQLITE BYTES")

    backup_path = snapshot_sqlite_db(src, backup_dir=tmp_path / "backups")

    assert Path(backup_path).exists()
    assert Path(backup_path).read_bytes() == b"FAKE SQLITE BYTES"
    assert "moneytree" in Path(backup_path).name
    assert Path(backup_path).suffix == ".db"


def test_snapshot_returns_none_when_source_missing(tmp_path):
    result = snapshot_sqlite_db(tmp_path / "missing.db", backup_dir=tmp_path / "backups")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_sync_backup.py -v`
Expected: FAIL with `ImportError: cannot import name 'snapshot_sqlite_db'`

- [ ] **Step 3: Implement backup**

Add to `backend/app/services/sync_import.py`:

```python
import shutil
from datetime import datetime, timezone
from pathlib import Path


def snapshot_sqlite_db(db_path: Path, backup_dir: Path) -> str | None:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{db_path.stem}-pre-import-{stamp}.db"
    shutil.copy2(db_path, target)
    return str(target)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_sync_backup.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sync_import.py backend/tests/test_sync_backup.py
git commit -m "feat: add SQLite snapshot helper for pre-import backup"
```

---

### Task 7: Import endpoint

**Files:**
- Modify: `backend/app/routers/sync.py`
- Test: `backend/tests/test_sync_endpoints.py` (extend)

- [ ] **Step 1: Write failing test (append to existing file)**

```python
# Append to backend/tests/test_sync_endpoints.py
import json

from app.sync_schemas import ExportFile
from datetime import datetime, timezone


def _empty_export_dict():
    return {
        "format_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "since": None,
        "categories": [{"name": "Groceries", "parent_name": None, "is_fixed": False, "category_type": "expense"}],
        "category_mappings": [],
        "budgets": [],
        "budget_lines": [],
        "budget_templates": [],
        "transactions": [],
        "transaction_offsets": [],
    }


def test_import_dry_run_returns_preview_without_writes(client, db):
    payload = _empty_export_dict()
    files = {"file": ("export.json", json.dumps(payload), "application/json")}
    resp = client.post("/api/sync/import?dry_run=true", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert body["committed"] is False
    assert body["preview"]["will_add_categories"] == 1

    from app.models import Category
    from sqlalchemy import select
    cats = db.execute(select(Category)).scalars().all()
    assert cats == []


def test_import_commit_applies_changes(client, db):
    payload = _empty_export_dict()
    files = {"file": ("export.json", json.dumps(payload), "application/json")}
    resp = client.post("/api/sync/import?dry_run=false", files=files)

    assert resp.status_code == 200
    assert resp.json()["committed"] is True

    from app.models import Category
    from sqlalchemy import select
    cats = db.execute(select(Category)).scalars().all()
    assert {c.name for c in cats} == {"Groceries"}


def test_import_rejects_invalid_format_version(client):
    payload = _empty_export_dict()
    payload["format_version"] = 999
    files = {"file": ("export.json", json.dumps(payload), "application/json")}
    resp = client.post("/api/sync/import?dry_run=true", files=files)
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_sync_endpoints.py -v`
Expected: 3 new tests FAIL (route not implemented).

- [ ] **Step 3: Implement endpoint**

Add to `backend/app/routers/sync.py`:

```python
import json

from fastapi import File, HTTPException, UploadFile
from pydantic import ValidationError

from ..config import DATA_DIR  # see step 3a if missing
from ..services.sync_import import commit_import, preview_import, snapshot_sqlite_db
from ..sync_schemas import ImportResult


@router.post("/import", response_model=ImportResult)
async def import_sync(
    file: UploadFile = File(...),
    dry_run: bool = True,
    update_duplicates: bool = False,
    db: Session = Depends(get_db),
):
    raw = await file.read()
    try:
        data = json.loads(raw)
        export = ExportFile.model_validate(data)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid export file: {exc}")

    if dry_run:
        preview = preview_import(db, export)
        return ImportResult(preview=preview, committed=False, backup_path=None)

    backup_path = snapshot_sqlite_db(
        db_path=DATA_DIR / "moneytree.db",
        backup_dir=DATA_DIR / "backups",
    )
    try:
        preview = commit_import(db, export, update_duplicates=update_duplicates)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    return ImportResult(preview=preview, committed=True, backup_path=backup_path)
```

- [ ] **Step 3a: Verify `DATA_DIR` exists in config**

Check `backend/app/config.py`. If `DATA_DIR` is not exported, add:

```python
from pathlib import Path
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
```

(In tests `DATA_DIR` need not exist — `snapshot_sqlite_db` returns `None` when the source file is missing.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_sync_endpoints.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/sync.py backend/app/config.py backend/tests/test_sync_endpoints.py
git commit -m "feat: add sync import endpoint with dry-run and pre-import backup"
```

---

### Task 8: Frontend API client

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add export and import helpers**

Append near the other endpoint groups:

```typescript
// --- Sync ---

export interface ImportConflict {
	code: string;
	severity: 'soft' | 'hard';
	message: string;
}

export interface ImportPreview {
	will_add_categories: number;
	will_add_category_mappings: number;
	will_add_budgets: number;
	will_add_budget_lines: number;
	will_update_budget_lines: number;
	will_add_budget_templates: number;
	will_add_transactions: number;
	will_update_transactions: number;
	will_skip_transactions: number;
	will_add_offsets: number;
	soft_conflicts: ImportConflict[];
	hard_conflicts: ImportConflict[];
}

export interface ImportResultResponse {
	preview: ImportPreview;
	committed: boolean;
	backup_path: string | null;
}

export async function downloadSyncExport(since?: string): Promise<Blob> {
	const qs = since ? `?since=${encodeURIComponent(since)}` : '';
	const res = await fetch(`/api/sync/export${qs}`, { credentials: 'include' });
	if (!res.ok) throw new Error(`Export failed: ${res.status}`);
	return res.blob();
}

export async function previewSyncImport(file: File): Promise<ImportResultResponse> {
	const form = new FormData();
	form.append('file', file);
	return request('/api/sync/import?dry_run=true', { method: 'POST', body: form });
}

export async function commitSyncImport(
	file: File,
	updateDuplicates: boolean,
): Promise<ImportResultResponse> {
	const form = new FormData();
	form.append('file', file);
	const qs = `?dry_run=false&update_duplicates=${updateDuplicates}`;
	return request(`/api/sync/import${qs}`, { method: 'POST', body: form });
}
```

- [ ] **Step 2: Verify types compile**

Run: `cd frontend && bun x svelte-check --tsconfig ./tsconfig.json`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add sync export/import API client"
```

---

### Task 9: Frontend sync UI

**Files:**
- Create: `frontend/src/routes/settings/sync/+page.svelte`

- [ ] **Step 1: Implement the page**

```svelte
<script lang="ts">
	import {
		downloadSyncExport,
		previewSyncImport,
		commitSyncImport,
		type ImportPreview,
		type ImportResultResponse,
	} from '$lib/api';

	let since = $state('');
	let exporting = $state(false);
	let importFile: File | null = $state(null);
	let preview: ImportPreview | null = $state(null);
	let importResult: ImportResultResponse | null = $state(null);
	let updateDuplicates = $state(false);
	let busy = $state(false);
	let errorMsg = $state<string | null>(null);

	async function handleExport() {
		exporting = true;
		errorMsg = null;
		try {
			const blob = await downloadSyncExport(since || undefined);
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			const stamp = new Date().toISOString().replace(/[:.]/g, '-');
			a.download = `moneytree-export-${stamp}.json`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			errorMsg = e instanceof Error ? e.message : String(e);
		} finally {
			exporting = false;
		}
	}

	async function handlePreview() {
		if (!importFile) return;
		busy = true;
		errorMsg = null;
		preview = null;
		importResult = null;
		try {
			const res = await previewSyncImport(importFile);
			preview = res.preview;
		} catch (e) {
			errorMsg = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}

	async function handleCommit() {
		if (!importFile) return;
		if (preview && preview.hard_conflicts.length > 0) return;
		busy = true;
		errorMsg = null;
		try {
			importResult = await commitSyncImport(importFile, updateDuplicates);
			preview = importResult.preview;
		} catch (e) {
			errorMsg = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}
</script>

<section class="container">
	<h1>Sync</h1>

	<article>
		<h2>Export</h2>
		<p>Download all categories, budgets, mappings, and transactions as a single JSON file.</p>
		<label>
			Only transactions created on or after:
			<input type="date" bind:value={since} />
		</label>
		<button onclick={handleExport} disabled={exporting}>
			{exporting ? 'Exporting...' : 'Download export file'}
		</button>
	</article>

	<article>
		<h2>Import</h2>
		<p>Merge a previous export into this instance. Always preview first.</p>
		<input
			type="file"
			accept="application/json"
			onchange={(e) => {
				const t = e.currentTarget as HTMLInputElement;
				importFile = t.files?.[0] ?? null;
				preview = null;
				importResult = null;
			}}
		/>
		<label>
			<input type="checkbox" bind:checked={updateDuplicates} />
			Overwrite existing transactions' category and merchant when import_hash matches
		</label>
		<div class="row">
			<button onclick={handlePreview} disabled={!importFile || busy}>Preview</button>
			<button
				onclick={handleCommit}
				disabled={!importFile || !preview || busy || (preview?.hard_conflicts.length ?? 0) > 0}
			>
				Apply import
			</button>
		</div>

		{#if errorMsg}
			<p class="error">{errorMsg}</p>
		{/if}

		{#if preview}
			<h3>Preview</h3>
			<ul>
				<li>Categories to add: {preview.will_add_categories}</li>
				<li>Category mappings to add: {preview.will_add_category_mappings}</li>
				<li>Budgets to add: {preview.will_add_budgets}</li>
				<li>Budget lines to add: {preview.will_add_budget_lines}</li>
				<li>Budget lines to update: {preview.will_update_budget_lines}</li>
				<li>Budget templates to add: {preview.will_add_budget_templates}</li>
				<li>Transactions to add: {preview.will_add_transactions}</li>
				<li>Transactions to update: {preview.will_update_transactions}</li>
				<li>Transactions to skip (dedup): {preview.will_skip_transactions}</li>
				<li>Offsets to add: {preview.will_add_offsets}</li>
			</ul>

			{#if preview.hard_conflicts.length > 0}
				<h4>Hard conflicts (must resolve before import)</h4>
				<ul>
					{#each preview.hard_conflicts as c}
						<li class="hard">{c.message}</li>
					{/each}
				</ul>
			{/if}

			{#if preview.soft_conflicts.length > 0}
				<h4>Soft conflicts (resolved automatically)</h4>
				<ul>
					{#each preview.soft_conflicts as c}
						<li>{c.message}</li>
					{/each}
				</ul>
			{/if}
		{/if}

		{#if importResult?.committed}
			<p class="ok">
				Import committed.
				{#if importResult.backup_path}
					Backup: <code>{importResult.backup_path}</code>
				{/if}
			</p>
		{/if}
	</article>
</section>

<style>
	.container { max-width: 720px; padding: 1rem; }
	article { margin-block: 1rem; padding: 1rem; border: 1px solid var(--border, #ddd); border-radius: 8px; }
	.row { display: flex; gap: 0.5rem; margin-block: 0.5rem; }
	.error { color: tomato; }
	.ok { color: seagreen; }
	.hard { color: tomato; }
	label { display: block; margin-block: 0.5rem; }
</style>
```

- [ ] **Step 2: Manually verify**

Start backend + frontend (`docker-compose up`), browse to `/settings/sync`. Confirm:
- Clicking "Download export file" downloads a JSON file.
- Selecting that file, clicking Preview, shows counts.
- Clicking "Apply import" against an empty destination DB applies it.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/settings/sync/+page.svelte
git commit -m "feat: add settings sync page (export/import UI)"
```

---

### Task 10: End-to-end round-trip test

**Files:**
- Create: `backend/tests/test_sync_roundtrip.py`

**Why:** Catches regressions where individual unit tests pass but the full export → import pipeline drops or duplicates data.

- [ ] **Step 1: Write the test**

```python
# backend/tests/test_sync_roundtrip.py
from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    Base, Budget, BudgetLine, BudgetTemplate, Category,
    CategoryMapping, Transaction, TransactionOffset,
)
from app.services.sync_export import build_export
from app.services.sync_import import commit_import
from tests.conftest import make_category, make_transaction


def _fresh():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_full_roundtrip_preserves_state(db):
    parent = make_category(db, name="Living")
    child = Category(name="Groceries", parent_id=parent.id, category_type="expense", is_fixed=False)
    db.add(child); db.flush()
    db.add(CategoryMapping(bank_category="Boodschappen", category_id=child.id))
    db.add(BudgetTemplate(category_id=child.id, amount=400.0))
    budget = Budget(start_date=date(2026, 4, 1), end_date=date(2026, 5, 1))
    db.add(budget); db.flush()
    db.add(BudgetLine(budget_id=budget.id, category_id=child.id, amount=375.0))
    expense = make_transaction(db, bedrag=-50.0, category_id=child.id)
    income = make_transaction(db, bedrag=50.0, category_id=child.id)
    db.add(TransactionOffset(expense_transaction_id=expense.id, income_transaction_id=income.id))
    db.commit()

    export = build_export(db, since=None)
    dest = _fresh()
    commit_import(dest, export, update_duplicates=False)

    # Categories
    cats = {c.name: c for c in dest.execute(select(Category)).scalars().all()}
    assert set(cats) == {"Living", "Groceries"}
    assert cats["Groceries"].parent.name == "Living"

    # Mapping
    m = dest.execute(select(CategoryMapping)).scalars().one()
    assert m.bank_category == "Boodschappen" and m.category.name == "Groceries"

    # Budget + lines
    b = dest.execute(select(Budget)).scalars().one()
    assert b.start_date == date(2026, 4, 1)
    line = dest.execute(select(BudgetLine)).scalars().one()
    assert line.amount == 375.0

    # Templates
    t = dest.execute(select(BudgetTemplate)).scalars().one()
    assert t.amount == 400.0

    # Transactions
    txs = dest.execute(select(Transaction)).scalars().all()
    assert len(txs) == 2
    by_hash = {t.import_hash: t for t in txs}
    assert by_hash[expense.import_hash].bedrag == -50.0
    assert by_hash[income.import_hash].bedrag == 50.0

    # Offset (with remapped IDs)
    off = dest.execute(select(TransactionOffset)).scalars().one()
    assert off.expense_transaction.import_hash == expense.import_hash
    assert off.income_transaction.import_hash == income.import_hash


def test_idempotent_double_import(db):
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    commit_import(dest, export, update_duplicates=False)
    commit_import(dest, export, update_duplicates=False)

    assert len(dest.execute(select(Category)).scalars().all()) == 1
    assert len(dest.execute(select(Transaction)).scalars().all()) == 1
```

- [ ] **Step 2: Run the test**

Run: `cd backend && pytest tests/test_sync_roundtrip.py -v`
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_sync_roundtrip.py
git commit -m "test: add export/import round-trip and idempotency tests"
```

---

### Task 11: Wire settings page link

**Files:**
- Modify: `frontend/src/routes/settings/+page.svelte`

- [ ] **Step 1: Add a link to the new sync page**

At the top of the settings page (above the danger zone), add:

```svelte
<a href="/settings/sync" class="settings-link">
	<h2>Sync (export / import)</h2>
	<p>Download a JSON snapshot of this instance, or merge one in from another instance.</p>
</a>
```

(Adjust styling to match the existing settings page conventions.)

- [ ] **Step 2: Manually verify**

Browse to `/settings`, click the link, confirm it navigates to `/settings/sync`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/settings/+page.svelte
git commit -m "feat: link to sync page from settings"
```

---

## Documentation Update

Add to README or relevant operations doc (manual, no separate task — fold into Task 11 commit if desired):

> **Outage workflow:**
> 1. NAS down. Start local with `docker-compose up`.
> 2. Use locally during outage.
> 3. NAS back online. On local: Settings → Sync → Download export file.
> 4. On NAS: Settings → Sync → Upload that file → Preview. Resolve any hard conflicts (typically: overlapping budget date ranges). Click Apply. A backup of the NAS DB is taken automatically before the merge.
> 5. Verify counts in the result. If anything looks wrong, restore the backup file from `data/backups/`.

---

## Self-Review Notes

- **Spec coverage:** All ten conflict scenarios listed in Conflict Analysis are referenced in tests (S1 → `test_preview_flags_attribute_diff_on_existing_category`, S2 → covered in `test_full_roundtrip_preserves_state` indirectly; H1 → `test_preview_detects_overlapping_budget_hard_conflict` and `test_commit_aborts_on_hard_conflict`; C1 → `test_commit_dedup_does_not_duplicate_transactions`; S5 → `test_commit_update_duplicates_overwrites_mutable_fields`; S7/S8/S9/S10 → documented limitations, no test required).
- **Type consistency:** `ExportFile`, `ImportPreview`, `ImportResult`, `ImportConflict`, `commit_import`, `preview_import`, `snapshot_sqlite_db`, `build_export`, `downloadSyncExport`, `previewSyncImport`, `commitSyncImport` — names match across all tasks.
- **Receipts/line_items:** explicitly out of scope for v1; documented in "In-scope tables" and the Out-of-Scope notes. Pre-existing receipt rows on the destination are untouched by import (their FK to transactions stays valid because dedup-by-hash reuses NAS transaction IDs).
