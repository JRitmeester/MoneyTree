# Financial Insights Phases 1-3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every dashboard number correct by flagging internal transfers, add a checking-balance-over-time chart, and add a savings-capacity view with an incidental-expense flag.

**Architecture:** New `own_accounts` table drives automatic `is_internal_transfer` flagging on import and backfill; all analytics endpoints exclude flagged transactions. A manual `is_incidental` flag on transactions feeds a new savings-capacity endpoint that reports structural vs raw monthly net with trailing averages. Balance history is derived from the already-stored `saldo_voor_boeking` column.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic + pytest (backend), SvelteKit + Svelte 5 runes + vitest (frontend), SQLite.

**Spec:** `docs/superpowers/specs/2026-08-27-financial-insights-design.md` (this plan covers spec build-order phases 1, 2, and 3; phases 4-6 get their own plan later).

## Global Constraints

- No em-dashes anywhere (code comments, commit messages, UI copy). Use commas, colons, or parentheses.
- Files stay under 800 lines; extract helpers into `backend/app/services/` modules rather than growing routers.
- Conventional commit format: `<type>: <description>` (feat, fix, refactor, docs, test, chore). No attribution footer.
- TDD: every behavior change gets a failing test first.
- Backend tests run from `backend/`: `python -m pytest tests/ -v`. The test DB is built from `Base.metadata.create_all`, so model changes apply to tests without migrations; migrations matter only for the real DB.
- Frontend checks run from `frontend/`: `npm run check` (svelte-check must stay at 0 errors, 0 warnings) and `npx vitest run` for unit tests.
- Currency values rounded to 2 decimals in API responses.
- Known accepted gap (do NOT implement here): the new transaction flags and `own_accounts` are not propagated through the device-sync feature (`sync_export.py` / `sync_import.py`). Follow-up work, out of scope.

---

### Task 1: OwnAccount model + migration + transaction flag columns

**Files:**
- Modify: `backend/app/models.py` (add `OwnAccount` class; add 3 columns to `Transaction`)
- Create: `backend/alembic/versions/j0k1l2m3n4o5_add_own_accounts_and_transaction_flags.py`
- Modify: `backend/tests/conftest.py` (extend `make_transaction`)
- Test: `backend/tests/test_own_accounts.py`

**Interfaces:**
- Consumes: existing `Base`, `Transaction`, `_utcnow` in `models.py`.
- Produces: `OwnAccount` model with fields `id: int`, `iban: str` (unique), `name: str`, `account_type: str` ("checking" | "savings"), `starting_balance: float | None`, `starting_balance_date: date | None`, `created_at: datetime`. `Transaction` gains `is_internal_transfer: bool`, `is_internal_transfer_manual: bool`, `is_incidental: bool` (all default False, non-null). `make_transaction` gains keyword args `datum`, `tegenrekening`, `saldo_voor_boeking`, `volgnummer`, `is_incidental`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_own_accounts.py`:

```python
from datetime import date

from sqlalchemy.orm import Session

from app.models import OwnAccount, Transaction

from .conftest import make_transaction


class TestOwnAccountModel:
    def test_own_account_persists_all_fields(self, db: Session):
        acc = OwnAccount(
            iban="NL26ASNB8831527878",
            name="Betaalrekening",
            account_type="checking",
        )
        savings = OwnAccount(
            iban="NL00ASNB0000000002",
            name="Spaarrekening",
            account_type="savings",
            starting_balance=5000.0,
            starting_balance_date=date(2026, 4, 1),
        )
        db.add_all([acc, savings])
        db.flush()

        loaded = db.get(OwnAccount, savings.id)
        assert loaded.iban == "NL00ASNB0000000002"
        assert loaded.account_type == "savings"
        assert loaded.starting_balance == 5000.0
        assert loaded.starting_balance_date == date(2026, 4, 1)
        assert acc.starting_balance is None

    def test_transaction_flags_default_false(self, db: Session):
        tx = make_transaction(db)
        assert tx.is_internal_transfer is False
        assert tx.is_internal_transfer_manual is False
        assert tx.is_incidental is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_own_accounts.py -v`
Expected: FAIL with `ImportError: cannot import name 'OwnAccount'`

- [ ] **Step 3: Add the model and columns**

In `backend/app/models.py`, add to the `Transaction` class after the `category_id` column (line 46):

```python
    is_internal_transfer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_internal_transfer_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_incidental: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

Add a new class after `SyncEvent` (end of file):

```python
class OwnAccount(Base):
    """A bank account owned by the user. Transactions whose counterparty
    IBAN matches an own account are internal transfers, not income/expenses."""
    __tablename__ = "own_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    iban: Mapped[str] = mapped_column(String(34), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_type: Mapped[str] = mapped_column(String(10), nullable=False)  # "checking" | "savings"
    starting_balance: Mapped[float | None] = mapped_column(Float)
    starting_balance_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
```

- [ ] **Step 4: Extend the test factory**

In `backend/tests/conftest.py`, replace the `make_transaction` signature and body so callers can control the fields these features need (all new args are keyword-only with defaults, existing tests keep working):

```python
def make_transaction(
    db: Session,
    *,
    bedrag: float = -10.0,
    categorie: str = "Boodschappen",
    category_id: int | None = None,
    naam: str | None = "Test Store",
    merchant_name: str | None = None,
    omschrijving: str = "Test transaction",
    datum: date = date(2025, 1, 15),
    tegenrekening: str | None = None,
    saldo_voor_boeking: float = 1000.0,
    volgnummer: str = "001",
    is_incidental: bool = False,
) -> Transaction:
    tx = Transaction(
        datum=datum,
        rekening="NL00TEST0000000001",
        tegenrekening=tegenrekening,
        naam=naam,
        valuta_saldo="EUR",
        saldo_voor_boeking=saldo_voor_boeking,
        valuta="EUR",
        bedrag=bedrag,
        verwerkingsdatum=datum,
        valutadatum=datum,
        code="GT",
        type="BET",
        volgnummer=volgnummer,
        omschrijving=omschrijving,
        afschriftnummer="001",
        categorie=categorie,
        merchant_name=merchant_name,
        import_hash=uuid.uuid4().hex,
        category_id=category_id,
        is_incidental=is_incidental,
    )
    db.add(tx)
    db.flush()
    return tx
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_own_accounts.py -v`
Expected: 2 PASS

Run: `cd backend && python -m pytest tests/ -v`
Expected: all existing tests still PASS (factory change is backward compatible)

- [ ] **Step 6: Write the migration**

First confirm the current head: `cd backend && python -m alembic heads` (expected: `i9j0k1l2m3n4`; if different, use that value as `down_revision`).

Create `backend/alembic/versions/j0k1l2m3n4o5_add_own_accounts_and_transaction_flags.py`:

```python
"""add own_accounts table and transaction transfer/incidental flags

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-08-27 15:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'j0k1l2m3n4o5'
down_revision: Union[str, None] = 'i9j0k1l2m3n4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'own_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('iban', sa.String(length=34), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('account_type', sa.String(length=10), nullable=False),
        sa.Column('starting_balance', sa.Float(), nullable=True),
        sa.Column('starting_balance_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('iban'),
    )
    op.add_column('transactions', sa.Column(
        'is_internal_transfer', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('transactions', sa.Column(
        'is_internal_transfer_manual', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('transactions', sa.Column(
        'is_incidental', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('transactions', 'is_incidental')
    op.drop_column('transactions', 'is_internal_transfer_manual')
    op.drop_column('transactions', 'is_internal_transfer')
    op.drop_table('own_accounts')
```

- [ ] **Step 7: Verify the migration runs**

Run: `cd backend && python -m alembic upgrade head && python -m alembic history | head -3`
Expected: no error; `j0k1l2m3n4o5` is the new head. (This touches the real `moneytree.db`; the migration is additive and safe.)

- [ ] **Step 8: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/j0k1l2m3n4o5_add_own_accounts_and_transaction_flags.py backend/tests/conftest.py backend/tests/test_own_accounts.py
git commit -m "feat(accounts): add OwnAccount model and transaction transfer/incidental flags"
```

---

### Task 2: Transfer-flagging service

**Files:**
- Create: `backend/app/services/transfers.py`
- Test: `backend/tests/test_transfers.py`

**Interfaces:**
- Consumes: `OwnAccount`, `Transaction` models.
- Produces (used by Tasks 3, 4, 5):
  - `normalize_iban(value: str) -> str`
  - `own_ibans(db: Session) -> set[str]` (normalized)
  - `is_internal(tx: Transaction, ibans: set[str]) -> bool`
  - `backfill_internal_transfers(db: Session) -> int` (returns count of rows changed; never touches rows where `is_internal_transfer_manual` is True; does not commit, caller commits)
  - `savings_balance(db: Session) -> SavingsBalanceResult | None` where `SavingsBalanceResult` is a frozen dataclass with `balance: float`, `is_net_only: bool`, `account_name: str`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_transfers.py`:

```python
from datetime import date

from sqlalchemy.orm import Session

from app.models import OwnAccount
from app.services.transfers import (
    backfill_internal_transfers,
    normalize_iban,
    own_ibans,
    savings_balance,
)

from .conftest import make_transaction

SAVINGS_IBAN = "NL00ASNB0000000002"


def add_savings_account(db, *, starting_balance=None, starting_balance_date=None):
    acc = OwnAccount(
        iban=SAVINGS_IBAN,
        name="Spaarrekening",
        account_type="savings",
        starting_balance=starting_balance,
        starting_balance_date=starting_balance_date,
    )
    db.add(acc)
    db.flush()
    return acc


class TestNormalizeIban:
    def test_strips_spaces_and_uppercases(self):
        assert normalize_iban("nl26 asnb 8831 5278 78") == "NL26ASNB8831527878"


class TestBackfill:
    def test_flags_matching_counterparty(self, db: Session):
        add_savings_account(db)
        to_savings = make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN)
        unrelated = make_transaction(db, bedrag=-500.0, tegenrekening="NL99BANK0000000009")
        no_counterparty = make_transaction(db, bedrag=-25.0, tegenrekening=None)

        changed = backfill_internal_transfers(db)

        assert changed == 1
        assert to_savings.is_internal_transfer is True
        assert unrelated.is_internal_transfer is False
        assert no_counterparty.is_internal_transfer is False

    def test_unflags_when_account_removed(self, db: Session):
        tx = make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN)
        tx.is_internal_transfer = True
        db.flush()

        changed = backfill_internal_transfers(db)  # no own accounts exist

        assert changed == 1
        assert tx.is_internal_transfer is False

    def test_skips_manual_overrides(self, db: Session):
        add_savings_account(db)
        tx = make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN)
        tx.is_internal_transfer = False
        tx.is_internal_transfer_manual = True
        db.flush()

        changed = backfill_internal_transfers(db)

        assert changed == 0
        assert tx.is_internal_transfer is False

    def test_matches_despite_spacing_differences(self, db: Session):
        add_savings_account(db)
        tx = make_transaction(db, bedrag=-100.0, tegenrekening="nl00 asnb 0000 0000 02")
        backfill_internal_transfers(db)
        assert tx.is_internal_transfer is True


class TestSavingsBalance:
    def test_none_without_savings_account(self, db: Session):
        assert savings_balance(db) is None

    def test_net_only_without_starting_balance(self, db: Session):
        add_savings_account(db)
        make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN)
        make_transaction(db, bedrag=200.0, tegenrekening=SAVINGS_IBAN)
        backfill_internal_transfers(db)

        result = savings_balance(db)
        assert result.is_net_only is True
        assert result.balance == 300.0  # 500 in, 200 back out

    def test_starting_balance_and_date_cutoff(self, db: Session):
        add_savings_account(db, starting_balance=1000.0, starting_balance_date=date(2025, 1, 10))
        make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN, datum=date(2025, 1, 15))
        make_transaction(db, bedrag=-999.0, tegenrekening=SAVINGS_IBAN, datum=date(2025, 1, 5))
        backfill_internal_transfers(db)

        result = savings_balance(db)
        assert result.is_net_only is False
        assert result.balance == 1500.0  # 1000 start + 500; the Jan 5 transfer predates the cutoff
        assert result.account_name == "Spaarrekening"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_transfers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.transfers'`

- [ ] **Step 3: Implement the service**

Create `backend/app/services/transfers.py`:

```python
"""Internal-transfer detection between the user's own accounts.

Transactions whose counterparty IBAN matches an OwnAccount are transfers,
not income or expenses, and are excluded from all analytics."""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import OwnAccount, Transaction


def normalize_iban(value: str) -> str:
    return value.replace(" ", "").upper()


def own_ibans(db: Session) -> set[str]:
    accounts = db.execute(select(OwnAccount)).scalars().all()
    return {normalize_iban(a.iban) for a in accounts}


def is_internal(tx: Transaction, ibans: set[str]) -> bool:
    if not tx.tegenrekening:
        return False
    return normalize_iban(tx.tegenrekening) in ibans


def backfill_internal_transfers(db: Session) -> int:
    """Re-derive the flag for every transaction from the current own-account
    set. Rows the user overrode manually are never touched. Does not commit."""
    ibans = own_ibans(db)
    changed = 0
    txs = db.execute(
        select(Transaction).where(Transaction.is_internal_transfer_manual.is_(False))
    ).scalars().all()
    for tx in txs:
        flag = is_internal(tx, ibans)
        if tx.is_internal_transfer != flag:
            tx.is_internal_transfer = flag
            changed += 1
    return changed


@dataclass(frozen=True)
class SavingsBalanceResult:
    balance: float
    is_net_only: bool  # True when no starting balance is configured
    account_name: str


def savings_balance(db: Session) -> SavingsBalanceResult | None:
    """Inferred savings balance: starting balance plus net transfers from
    checking since the starting-balance date. None when no savings account
    is configured."""
    savings = db.execute(
        select(OwnAccount).where(OwnAccount.account_type == "savings")
    ).scalars().first()
    if savings is None:
        return None

    savings_iban = normalize_iban(savings.iban)
    query = select(Transaction).where(Transaction.is_internal_transfer.is_(True))
    if savings.starting_balance_date is not None:
        query = query.where(Transaction.datum >= savings.starting_balance_date)

    net_in = 0.0
    for tx in db.execute(query).scalars().all():
        if tx.tegenrekening and normalize_iban(tx.tegenrekening) == savings_iban:
            # Negative bedrag on checking means money arrived in savings.
            net_in += -tx.bedrag

    has_start = savings.starting_balance is not None
    base = savings.starting_balance if has_start else 0.0
    return SavingsBalanceResult(
        balance=round(base + net_in, 2),
        is_net_only=not has_start,
        account_name=savings.name,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_transfers.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/transfers.py backend/tests/test_transfers.py
git commit -m "feat(transfers): add internal-transfer flagging and savings-balance service"
```

---

### Task 3: Own-accounts CRUD API

**Files:**
- Modify: `backend/app/schemas.py` (append own-account schemas)
- Create: `backend/app/routers/own_accounts.py`
- Modify: `backend/app/main.py` (import + include router)
- Modify: `backend/app/routers/settings.py` (delete-everything also clears own_accounts)
- Test: `backend/tests/test_own_accounts.py` (extend)

**Interfaces:**
- Consumes: `backfill_internal_transfers` from Task 2.
- Produces REST endpoints under `/api/own-accounts`:
  - `GET /api/own-accounts` returns `list[OwnAccountOut]`
  - `POST /api/own-accounts` body `OwnAccountCreate` returns `OwnAccountOut` (201-style, default 200 is fine); runs backfill
  - `PATCH /api/own-accounts/{id}` body `OwnAccountUpdate` (all fields optional); runs backfill when iban changes
  - `DELETE /api/own-accounts/{id}`; runs backfill
- Produces schemas: `OwnAccountCreate {iban: str, name: str, account_type: Literal["checking","savings"], starting_balance: float | None, starting_balance_date: date | None}`, `OwnAccountUpdate` (same, all optional), `OwnAccountOut` (adds `id`, `created_at`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_own_accounts.py`:

```python
class TestOwnAccountsApi:
    def test_create_and_list(self, client, db: Session):
        resp = client.post("/api/own-accounts", json={
            "iban": "nl26 asnb 8831 5278 78",
            "name": "Betaalrekening",
            "account_type": "checking",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["iban"] == "NL26ASNB8831527878"  # normalized on create

        resp = client.get("/api/own-accounts")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_create_rejects_bad_account_type(self, client):
        resp = client.post("/api/own-accounts", json={
            "iban": "NL26ASNB8831527878",
            "name": "X",
            "account_type": "bitcoin",
        })
        assert resp.status_code == 422

    def test_create_rejects_duplicate_iban(self, client):
        payload = {"iban": "NL26ASNB8831527878", "name": "A", "account_type": "checking"}
        assert client.post("/api/own-accounts", json=payload).status_code == 200
        resp = client.post("/api/own-accounts", json=payload)
        assert resp.status_code == 409

    def test_create_triggers_backfill(self, client, db: Session):
        tx = make_transaction(db, bedrag=-500.0, tegenrekening="NL00ASNB0000000002")
        db.commit()
        resp = client.post("/api/own-accounts", json={
            "iban": "NL00ASNB0000000002",
            "name": "Spaarrekening",
            "account_type": "savings",
        })
        assert resp.status_code == 200
        db.refresh(tx)
        assert tx.is_internal_transfer is True

    def test_delete_triggers_backfill(self, client, db: Session):
        tx = make_transaction(db, bedrag=-500.0, tegenrekening="NL00ASNB0000000002")
        db.commit()
        created = client.post("/api/own-accounts", json={
            "iban": "NL00ASNB0000000002", "name": "S", "account_type": "savings",
        }).json()
        resp = client.delete(f"/api/own-accounts/{created['id']}")
        assert resp.status_code == 200
        db.refresh(tx)
        assert tx.is_internal_transfer is False

    def test_patch_updates_starting_balance(self, client):
        created = client.post("/api/own-accounts", json={
            "iban": "NL00ASNB0000000002", "name": "S", "account_type": "savings",
        }).json()
        resp = client.patch(f"/api/own-accounts/{created['id']}", json={
            "starting_balance": 2500.0,
            "starting_balance_date": "2026-04-01",
        })
        assert resp.status_code == 200
        assert resp.json()["starting_balance"] == 2500.0

    def test_patch_unknown_id_404(self, client):
        assert client.patch("/api/own-accounts/999", json={"name": "X"}).status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_own_accounts.py -v`
Expected: new tests FAIL with 404 (router not registered)

- [ ] **Step 3: Add schemas**

Append to `backend/app/schemas.py` (bottom of file):

```python
# --- Own Accounts ---


class OwnAccountCreate(BaseModel):
    iban: str = Field(min_length=8, max_length=34)
    name: str = Field(min_length=1, max_length=100)
    account_type: Literal["checking", "savings"]
    starting_balance: Optional[float] = None
    starting_balance_date: Optional[date] = None


class OwnAccountUpdate(BaseModel):
    iban: Optional[str] = Field(default=None, min_length=8, max_length=34)
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    account_type: Optional[Literal["checking", "savings"]] = None
    starting_balance: Optional[float] = None
    starting_balance_date: Optional[date] = None


class OwnAccountOut(BaseModel):
    id: int
    iban: str
    name: str
    account_type: str
    starting_balance: Optional[float]
    starting_balance_date: Optional[date]
    created_at: datetime

    model_config = {"from_attributes": True}
```

Check the imports at the top of `schemas.py`: ensure `Literal` is imported from `typing` and `Field` from `pydantic`; add them if missing.

- [ ] **Step 4: Implement the router**

Create `backend/app/routers/own_accounts.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import OwnAccount
from ..schemas import OwnAccountCreate, OwnAccountOut, OwnAccountUpdate
from ..services.transfers import backfill_internal_transfers, normalize_iban

router = APIRouter(
    prefix="/api/own-accounts", tags=["own-accounts"], dependencies=[Depends(require_auth)]
)


@router.get("", response_model=list[OwnAccountOut])
def list_own_accounts(db: Session = Depends(get_db)):
    return db.execute(select(OwnAccount).order_by(OwnAccount.id)).scalars().all()


@router.post("", response_model=OwnAccountOut)
def create_own_account(data: OwnAccountCreate, db: Session = Depends(get_db)):
    iban = normalize_iban(data.iban)
    existing = db.execute(
        select(OwnAccount).where(OwnAccount.iban == iban)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this IBAN already exists")

    account = OwnAccount(
        iban=iban,
        name=data.name,
        account_type=data.account_type,
        starting_balance=data.starting_balance,
        starting_balance_date=data.starting_balance_date,
    )
    db.add(account)
    db.flush()
    backfill_internal_transfers(db)
    db.commit()
    db.refresh(account)
    return account


@router.patch("/{account_id}", response_model=OwnAccountOut)
def update_own_account(account_id: int, data: OwnAccountUpdate, db: Session = Depends(get_db)):
    account = db.get(OwnAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    iban_changed = False
    updates = data.model_dump(exclude_unset=True)
    if "iban" in updates and updates["iban"] is not None:
        updates["iban"] = normalize_iban(updates["iban"])
        iban_changed = updates["iban"] != account.iban
    for key, value in updates.items():
        setattr(account, key, value)

    if iban_changed:
        db.flush()
        backfill_internal_transfers(db)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}")
def delete_own_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(OwnAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    db.delete(account)
    db.flush()
    backfill_internal_transfers(db)
    db.commit()
    return {"ok": True}
```

- [ ] **Step 5: Register the router**

In `backend/app/main.py`: add `own_accounts` to the `from .routers import (...)` list (alphabetical position, after `line_items`) and add `app.include_router(own_accounts.router)` next to the other `include_router` calls.

In `backend/app/routers/settings.py`: find the delete-everything endpoint, read how it deletes other tables, and add an `OwnAccount` deletion in the same style (import `OwnAccount` from `..models`). Own accounts are user data and must be wiped with everything else.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_own_accounts.py tests/test_transfers.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas.py backend/app/routers/own_accounts.py backend/app/main.py backend/app/routers/settings.py backend/tests/test_own_accounts.py
git commit -m "feat(accounts): own-accounts CRUD API with transfer backfill"
```

---

### Task 4: Flag transfers on CSV import; expose flags on the transactions API

**Files:**
- Modify: `backend/app/routers/transactions.py` (import flow, PATCH, new bulk endpoint)
- Modify: `backend/app/schemas.py` (`TransactionOut` gains the two flags; new `BulkIncidentalRequest`)
- Test: `backend/tests/test_transfers.py` (extend)

**Interfaces:**
- Consumes: `own_ibans`, `is_internal` from Task 2.
- Produces:
  - CSV import sets `is_internal_transfer` on new and updated rows (never on manual-override rows).
  - `PATCH /api/transactions/{id}` accepts `is_incidental: bool` and `is_internal_transfer: bool` (the latter also sets `is_internal_transfer_manual = True`).
  - `POST /api/transactions/bulk-incidental` body `{"transaction_ids": [int], "is_incidental": bool}` returns `{"updated": int}`.
  - `TransactionOut` (and therefore the list/detail endpoints) includes `is_internal_transfer: bool` and `is_incidental: bool`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_transfers.py`:

```python
class TestTransactionFlagsApi:
    def test_patch_is_incidental(self, client, db: Session):
        tx = make_transaction(db, bedrag=-1340.0)
        db.commit()
        resp = client.patch(f"/api/transactions/{tx.id}", json={"is_incidental": True})
        assert resp.status_code == 200
        assert resp.json()["is_incidental"] is True

    def test_patch_transfer_flag_sets_manual(self, client, db: Session):
        tx = make_transaction(db, bedrag=-500.0)
        db.commit()
        resp = client.patch(f"/api/transactions/{tx.id}", json={"is_internal_transfer": True})
        assert resp.status_code == 200
        assert resp.json()["is_internal_transfer"] is True
        db.refresh(tx)
        assert tx.is_internal_transfer_manual is True

    def test_manual_flag_survives_backfill(self, client, db: Session):
        tx = make_transaction(db, bedrag=-500.0, tegenrekening="NL99BANK0000000009")
        db.commit()
        client.patch(f"/api/transactions/{tx.id}", json={"is_internal_transfer": True})
        changed = backfill_internal_transfers(db)
        db.refresh(tx)
        assert tx.is_internal_transfer is True
        assert changed == 0

    def test_bulk_incidental(self, client, db: Session):
        a = make_transaction(db, bedrag=-100.0)
        b = make_transaction(db, bedrag=-200.0)
        db.commit()
        resp = client.post("/api/transactions/bulk-incidental", json={
            "transaction_ids": [a.id, b.id, 99999],
            "is_incidental": True,
        })
        assert resp.status_code == 200
        assert resp.json()["updated"] == 2
        db.refresh(a)
        assert a.is_incidental is True

    def test_list_includes_flags(self, client, db: Session):
        make_transaction(db, bedrag=-100.0)
        db.commit()
        item = client.get("/api/transactions").json()["items"][0]
        assert item["is_internal_transfer"] is False
        assert item["is_incidental"] is False


class TestImportFlagsTransfers:
    def test_import_flags_transfer_rows(self, client, db: Session):
        db.add(OwnAccount(iban="NL00ASNB0000000002", name="Spaar", account_type="savings"))
        db.commit()
        csv_content = (
            '01-08-2026;NL00TEST0000000001;NL00ASNB0000000002;J TEST;;;;EUR;1000,00;EUR;'
            '-500,00;01-08-2026;01-08-2026;GT;OVB;001;;Huur naar spaarpot;0001;Overboeking\n'
            '02-08-2026;NL00TEST0000000001;NL99BANK0000000009;SHOP;;;;EUR;500,00;EUR;'
            '-25,00;02-08-2026;02-08-2026;GT;BEA;002;;Boodschappen;0001;Boodschappen\n'
        )
        resp = client.post(
            "/api/transactions/import",
            files={"file": ("test.csv", csv_content.encode(), "text/csv")},
        )
        assert resp.status_code == 200
        assert resp.json()["imported"] == 2
        from app.models import Transaction
        from sqlalchemy import select
        txs = db.execute(select(Transaction).order_by(Transaction.datum)).scalars().all()
        assert txs[0].is_internal_transfer is True
        assert txs[1].is_internal_transfer is False
```

Note: before relying on the CSV fixture above, open `backend/app/services/csv_parser.py` and check the exact column order (20 positional columns, `;` separated). Adjust the two fixture lines so datum, rekening, tegenrekening, bedrag, volgnummer, afschriftnummer, and categorie land in the columns the parser reads. The assertion structure stays the same.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_transfers.py -v`
Expected: new tests FAIL (PATCH ignores the fields, bulk endpoint 404, TransactionOut lacks keys)

- [ ] **Step 3: Extend TransactionOut and add the bulk schema**

In `backend/app/schemas.py`, inside `class TransactionOut`, after `has_receipt: bool = False`, add:

```python
    is_internal_transfer: bool = False
    is_incidental: bool = False
```

At the bottom of the file add:

```python
class BulkIncidentalRequest(BaseModel):
    transaction_ids: list[int] = Field(min_length=1)
    is_incidental: bool
```

- [ ] **Step 4: Implement the router changes**

In `backend/app/routers/transactions.py`:

1. Import the service and schema: add `from ..services.transfers import is_internal, own_ibans` and add `BulkIncidentalRequest` to the schemas import.
2. In `import_csv`, before the `for tx_data in parsed:` loop, add `ibans = own_ibans(db)`. Inside the loop set the flag on both paths:
   - in the `if update_duplicates:` branch, after the category re-resolve line: `if not existing.is_internal_transfer_manual: existing.is_internal_transfer = is_internal(existing, ibans)`
   - in the `if not existing:` branch, after `tx.category_id = ...`: `tx.is_internal_transfer = is_internal(tx, ibans)`
3. In `update_transaction` (the PATCH handler), after the `category_id` block, add:

```python
    if "is_incidental" in data:
        tx.is_incidental = bool(data["is_incidental"])

    if "is_internal_transfer" in data:
        tx.is_internal_transfer = bool(data["is_internal_transfer"])
        tx.is_internal_transfer_manual = True
```

4. Add the bulk endpoint (place it above the `/{transaction_id}` GET route to keep literal paths grouped before parameterized ones):

```python
@router.post("/bulk-incidental")
def bulk_set_incidental(payload: BulkIncidentalRequest, db: Session = Depends(get_db)):
    """Set the incidental flag on many transactions at once."""
    txs = db.execute(
        select(Transaction).where(Transaction.id.in_(payload.transaction_ids))
    ).scalars().all()
    for tx in txs:
        tx.is_incidental = payload.is_incidental
    db.commit()
    return {"updated": len(txs)}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_transfers.py -v`
Expected: all PASS. Also run the full suite: `python -m pytest tests/ -v` (all PASS).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/transactions.py backend/app/schemas.py backend/tests/test_transfers.py
git commit -m "feat(transfers): flag internal transfers on import, expose flags via transactions API"
```

---

### Task 5: Exclude transfers from all analytics; transfers line + savings balance on dashboard API

**Files:**
- Modify: `backend/app/routers/dashboard.py` (`_iter_expense_items`, `get_summary`, `get_monthly_trend`, `get_budget_vs_actual`, new `/savings-balance`)
- Modify: `backend/app/schemas.py` (`DashboardSummary` gains transfer fields; new `SavingsBalanceOut`)
- Test: `backend/tests/test_dashboard_insights.py` (new file)

**Interfaces:**
- Consumes: `savings_balance` from Task 2; flags from Task 1.
- Produces:
  - `DashboardSummary` gains `transfers_out: float = 0.0`, `transfers_in: float = 0.0`, `transfers_net: float = 0.0`; `total_income`, `total_expenses`, `net`, `transaction_count` now cover non-transfer transactions only.
  - `GET /api/dashboard/savings-balance` returns `SavingsBalanceOut {balance: float, is_net_only: bool, account_name: str} | null`.
  - `_iter_expense_items` yields no internal transfers, which fixes `/by-category`, `/by-category-children`, `/category/{id}/line-items`, and the expense side of `/budget-vs-actual` in one place.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_dashboard_insights.py`:

```python
from datetime import date

from sqlalchemy.orm import Session

from app.models import OwnAccount
from app.services.transfers import backfill_internal_transfers

from .conftest import make_transaction

SAVINGS_IBAN = "NL00ASNB0000000002"


def setup_savings(db, **kwargs):
    db.add(OwnAccount(iban=SAVINGS_IBAN, name="Spaar", account_type="savings", **kwargs))
    db.flush()


class TestSummaryExcludesTransfers:
    def test_transfers_not_income_or_expense(self, client, db: Session):
        setup_savings(db)
        make_transaction(db, bedrag=3000.0)                                  # salary
        make_transaction(db, bedrag=-100.0)                                  # real expense
        make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN)      # to savings
        make_transaction(db, bedrag=200.0, tegenrekening=SAVINGS_IBAN)       # back from savings
        backfill_internal_transfers(db)
        db.commit()

        body = client.get("/api/dashboard/summary").json()
        assert body["total_income"] == 3000.0
        assert body["total_expenses"] == 100.0
        assert body["net"] == 2900.0
        assert body["transaction_count"] == 2
        assert body["transfers_out"] == 500.0
        assert body["transfers_in"] == 200.0
        assert body["transfers_net"] == 300.0


class TestByCategoryExcludesTransfers:
    def test_transfer_not_in_category_spending(self, client, db: Session):
        setup_savings(db)
        make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN, categorie="Overboeking")
        backfill_internal_transfers(db)
        db.commit()
        assert client.get("/api/dashboard/by-category").json() == []


class TestMonthlyTrendExcludesTransfers:
    def test_trend_skips_transfers(self, client, db: Session):
        setup_savings(db)
        make_transaction(db, bedrag=-100.0, datum=date(2025, 1, 10))
        make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN, datum=date(2025, 1, 12))
        backfill_internal_transfers(db)
        db.commit()

        months = client.get("/api/dashboard/monthly-trend").json()
        jan = next(m for m in months if m["month"] == "2025-01")
        assert jan["expenses"] == 100.0


class TestSavingsBalanceEndpoint:
    def test_null_without_savings_account(self, client):
        resp = client.get("/api/dashboard/savings-balance")
        assert resp.status_code == 200
        assert resp.json() is None

    def test_balance_with_starting_balance(self, client, db: Session):
        setup_savings(db, starting_balance=1000.0, starting_balance_date=date(2025, 1, 1))
        make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN, datum=date(2025, 1, 15))
        backfill_internal_transfers(db)
        db.commit()

        body = client.get("/api/dashboard/savings-balance").json()
        assert body["balance"] == 1500.0
        assert body["is_net_only"] is False
        assert body["account_name"] == "Spaar"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_dashboard_insights.py -v`
Expected: FAIL (summary counts transfers, transfer fields missing, savings-balance 404)

- [ ] **Step 3: Implement**

In `backend/app/schemas.py`, add to `DashboardSummary`:

```python
    transfers_out: float = 0.0
    transfers_in: float = 0.0
    transfers_net: float = 0.0
```

and at the bottom:

```python
class SavingsBalanceOut(BaseModel):
    balance: float
    is_net_only: bool
    account_name: str
```

In `backend/app/routers/dashboard.py`:

1. Import: add `SavingsBalanceOut` to the schemas import and add `from ..services.transfers import savings_balance as compute_savings_balance`.
2. `_iter_expense_items`: add `.where(Transaction.is_internal_transfer.is_(False))` to both the `li_query` and the `no_receipt_query`.
3. `get_summary`: replace the aggregate block with:

```python
    transactions = db.execute(query).scalars().all()

    external = [tx for tx in transactions if not tx.is_internal_transfer]
    internal = [tx for tx in transactions if tx.is_internal_transfer]

    total_income = sum(tx.bedrag for tx in external if tx.bedrag > 0)
    total_expenses = sum(tx.bedrag for tx in external if tx.bedrag < 0)
    net = total_income + total_expenses

    transfers_out = sum(-tx.bedrag for tx in internal if tx.bedrag < 0)
    transfers_in = sum(tx.bedrag for tx in internal if tx.bedrag > 0)

    tx_ids = [tx.id for tx in external]
```

and extend the returned `DashboardSummary(...)` with `transaction_count=len(external)`, `transfers_out=round(transfers_out, 2)`, `transfers_in=round(transfers_in, 2)`, `transfers_net=round(transfers_out - transfers_in, 2)`.

4. `get_monthly_trend`: inside the `for tx in transactions:` loop, first line: `if tx.is_internal_transfer: continue`.
5. `get_budget_vs_actual`: add `.where(Transaction.is_internal_transfer.is_(False))` to `income_query` and `direct_income_query` (the expense side is already covered via `_iter_expense_items`).
6. New endpoint (place near `get_summary`):

```python
@router.get("/savings-balance", response_model=SavingsBalanceOut | None)
def get_savings_balance(db: Session = Depends(get_db)):
    """Inferred savings-account balance from starting balance plus net transfers."""
    result = compute_savings_balance(db)
    if result is None:
        return None
    return SavingsBalanceOut(
        balance=result.balance,
        is_net_only=result.is_net_only,
        account_name=result.account_name,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all PASS (including the pre-existing suite)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/dashboard.py backend/app/schemas.py backend/tests/test_dashboard_insights.py
git commit -m "feat(dashboard): exclude internal transfers from analytics, add transfers line and savings balance"
```

---

### Task 6: Balance-history endpoint

**Files:**
- Modify: `backend/app/routers/dashboard.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_dashboard_insights.py` (extend)

**Interfaces:**
- Produces: `GET /api/dashboard/balance-history?date_from&date_to` returning `list[BalancePoint]` where `BalancePoint {date: date, balance: float}`, one point per day that has transactions, balance = end-of-day checking balance.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_dashboard_insights.py`:

```python
class TestBalanceHistory:
    def test_daily_end_of_day_balance(self, client, db: Session):
        # Two transactions on the same day: the later volgnummer wins.
        make_transaction(db, datum=date(2025, 1, 10), saldo_voor_boeking=1000.0,
                         bedrag=-100.0, volgnummer="001")
        make_transaction(db, datum=date(2025, 1, 10), saldo_voor_boeking=900.0,
                         bedrag=-50.0, volgnummer="002")
        make_transaction(db, datum=date(2025, 1, 12), saldo_voor_boeking=850.0,
                         bedrag=200.0, volgnummer="003")
        db.commit()

        points = client.get("/api/dashboard/balance-history").json()
        assert points == [
            {"date": "2025-01-10", "balance": 850.0},
            {"date": "2025-01-12", "balance": 1050.0},
        ]

    def test_date_range_filter(self, client, db: Session):
        make_transaction(db, datum=date(2025, 1, 10), saldo_voor_boeking=1000.0, bedrag=-100.0)
        make_transaction(db, datum=date(2025, 2, 10), saldo_voor_boeking=900.0, bedrag=-100.0)
        db.commit()

        points = client.get(
            "/api/dashboard/balance-history?date_from=2025-02-01"
        ).json()
        assert len(points) == 1
        assert points[0]["date"] == "2025-02-10"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_dashboard_insights.py -v`
Expected: new tests FAIL with 404

- [ ] **Step 3: Implement**

In `backend/app/schemas.py`, bottom:

```python
class BalancePoint(BaseModel):
    date: date
    balance: float
```

In `backend/app/routers/dashboard.py` (import `BalancePoint`):

```python
@router.get("/balance-history", response_model=list[BalancePoint])
def get_balance_history(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
):
    """End-of-day checking balance per day, derived from saldo_voor_boeking.

    All transactions are loaded (not just the range) because a day's balance
    only exists on days with activity; the range filter applies afterwards."""
    txs = db.execute(select(Transaction)).scalars().all()

    def sort_key(tx: Transaction):
        try:
            vol = int(tx.volgnummer)
        except (TypeError, ValueError):
            vol = 0
        return (tx.datum, vol, tx.id)

    daily: dict[date, float] = {}
    for tx in sorted(txs, key=sort_key):
        daily[tx.datum] = round(tx.saldo_voor_boeking + tx.bedrag, 2)

    points = [BalancePoint(date=d, balance=b) for d, b in sorted(daily.items())]
    if date_from:
        points = [p for p in points if p.date >= date_from]
    if date_to:
        points = [p for p in points if p.date <= date_to]
    return points
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_dashboard_insights.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/dashboard.py backend/app/schemas.py backend/tests/test_dashboard_insights.py
git commit -m "feat(dashboard): balance-history endpoint from saldo_voor_boeking"
```

---

### Task 7: Savings-capacity endpoint

**Files:**
- Modify: `backend/app/routers/dashboard.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_dashboard_insights.py` (extend)

**Interfaces:**
- Produces: `GET /api/dashboard/savings-capacity?months=N` (default 6, 1..24) returning `SavingsCapacitySummary`:
  - `months: list[SavingsCapacityMonth]` with `month: str ("YYYY-MM")`, `partial: bool`, `income`, `expenses_total`, `expenses_structural`, `incidental`, `fixed`, `flexible`, `uncategorized`, `net_raw`, `net_structural` (all float)
  - `trailing_3_raw`, `trailing_3_structural`, `trailing_6_raw`, `trailing_6_structural`: `float | None` (None when fewer complete months exist than the window needs)
  - `current_month_projection: float | None` (always None in this plan; phase 4 fills it from confirmed recurring payments)
  - Internal transfers always excluded. A month is complete when the imported data fully covers it (first transaction date <= month start AND last transaction date >= month end). Averages use complete months only; the returned list is the last N months including partial ones, flagged.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_dashboard_insights.py`:

```python
class TestSavingsCapacity:
    def _seed_month(self, db, year, month, *, income=3000.0, spend=2000.0, incidental=0.0):
        from calendar import monthrange
        make_transaction(db, bedrag=income, datum=date(year, month, 1))
        make_transaction(db, bedrag=-spend, datum=date(year, month, 5))
        if incidental:
            make_transaction(db, bedrag=-incidental, datum=date(year, month, 6), is_incidental=True)
        # Anchor the month edges so completeness detection sees full coverage.
        make_transaction(db, bedrag=-1.0, datum=date(year, month, monthrange(year, month)[1]))

    def test_monthly_series_and_structural_net(self, client, db: Session):
        self._seed_month(db, 2025, 1, income=3000.0, spend=2000.0, incidental=500.0)
        db.commit()

        body = client.get("/api/dashboard/savings-capacity").json()
        jan = next(m for m in body["months"] if m["month"] == "2025-01")
        assert jan["income"] == 3000.0
        assert jan["expenses_total"] == 2501.0
        assert jan["incidental"] == 500.0
        assert jan["expenses_structural"] == 2001.0
        assert jan["net_raw"] == 499.0
        assert jan["net_structural"] == 999.0
        assert jan["partial"] is False

    def test_excludes_internal_transfers(self, client, db: Session):
        setup_savings(db)
        self._seed_month(db, 2025, 1)
        make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN, datum=date(2025, 1, 20))
        backfill_internal_transfers(db)
        db.commit()

        jan = next(m for m in client.get("/api/dashboard/savings-capacity").json()["months"]
                   if m["month"] == "2025-01")
        assert jan["expenses_total"] == 2001.0

    def test_partial_month_flagged_and_excluded_from_averages(self, client, db: Session):
        for m in (1, 2, 3):
            self._seed_month(db, 2025, m)
        # April only has data up to the 10th: partial.
        make_transaction(db, bedrag=-100.0, datum=date(2025, 4, 10))
        db.commit()

        body = client.get("/api/dashboard/savings-capacity").json()
        apr = next(m for m in body["months"] if m["month"] == "2025-04")
        assert apr["partial"] is True
        # Averages over the 3 complete months: each has net_raw 999.0.
        assert body["trailing_3_raw"] == 999.0
        assert body["trailing_6_raw"] is None  # only 3 complete months exist

    def test_fixed_flexible_uncategorized_split(self, client, db: Session):
        from .conftest import make_category
        from app.models import Category
        fixed_cat = Category(name="Huur", is_fixed=True, category_type="expense")
        flex_cat = Category(name="Boodschappen", is_fixed=False, category_type="expense")
        db.add_all([fixed_cat, flex_cat])
        db.flush()
        make_transaction(db, bedrag=-1200.0, datum=date(2025, 1, 2), category_id=fixed_cat.id)
        make_transaction(db, bedrag=-300.0, datum=date(2025, 1, 3), category_id=flex_cat.id)
        make_transaction(db, bedrag=-50.0, datum=date(2025, 1, 4), category_id=None)
        db.commit()

        jan = next(m for m in client.get("/api/dashboard/savings-capacity").json()["months"]
                   if m["month"] == "2025-01")
        assert jan["fixed"] == 1200.0
        assert jan["flexible"] == 300.0
        assert jan["uncategorized"] == 50.0

    def test_empty_database(self, client):
        body = client.get("/api/dashboard/savings-capacity").json()
        assert body["months"] == []
        assert body["trailing_3_structural"] is None
        assert body["current_month_projection"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_dashboard_insights.py -v`
Expected: new tests FAIL with 404

- [ ] **Step 3: Implement**

In `backend/app/schemas.py`, bottom:

```python
class SavingsCapacityMonth(BaseModel):
    month: str
    partial: bool
    income: float
    expenses_total: float
    expenses_structural: float
    incidental: float
    fixed: float
    flexible: float
    uncategorized: float
    net_raw: float
    net_structural: float


class SavingsCapacitySummary(BaseModel):
    months: list[SavingsCapacityMonth]
    trailing_3_raw: Optional[float]
    trailing_3_structural: Optional[float]
    trailing_6_raw: Optional[float]
    trailing_6_structural: Optional[float]
    current_month_projection: Optional[float] = None
```

In `backend/app/routers/dashboard.py` (import the two new schemas, plus `from calendar import monthrange`):

```python
def _month_bounds(month_key: str) -> tuple[date, date]:
    year, month = (int(p) for p in month_key.split("-"))
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


@router.get("/savings-capacity", response_model=SavingsCapacitySummary)
def get_savings_capacity(
    months: int = Query(6, ge=1, le=24),
    db: Session = Depends(get_db),
):
    """Monthly income vs structural expenses, transfers excluded.

    A month counts toward the trailing averages only when the imported data
    fully covers it. Incidental (one-off) expenses are reported separately."""
    txs = db.execute(
        select(Transaction).where(Transaction.is_internal_transfer.is_(False))
    ).scalars().all()

    empty = SavingsCapacitySummary(
        months=[], trailing_3_raw=None, trailing_3_structural=None,
        trailing_6_raw=None, trailing_6_structural=None,
    )
    if not txs:
        return empty

    min_datum = min(tx.datum for tx in txs)
    max_datum = max(tx.datum for tx in txs)

    buckets: dict[str, dict[str, float]] = {}
    for tx in txs:
        key = tx.datum.strftime("%Y-%m")
        b = buckets.setdefault(key, {
            "income": 0.0, "expenses_total": 0.0,
            "expenses_structural": 0.0, "incidental": 0.0,
        })
        if tx.bedrag > 0:
            b["income"] += tx.bedrag
        else:
            amount = abs(tx.bedrag)
            b["expenses_total"] += amount
            if tx.is_incidental:
                b["incidental"] += amount
            else:
                b["expenses_structural"] += amount

    # Fixed/flexible/uncategorized split, line-item aware, incidentals excluded.
    cat_id_to_cat, _ = _build_hierarchy(db)
    splits: dict[str, dict[str, float]] = {}
    for item in _iter_expense_items(db, None, None):
        if item.tx.is_incidental:
            continue
        s = splits.setdefault(item.tx.datum.strftime("%Y-%m"),
                              {"fixed": 0.0, "flexible": 0.0, "uncategorized": 0.0})
        if item.category_id is None:
            s["uncategorized"] += item.amount
        else:
            cat = cat_id_to_cat.get(item.category_id)
            s["fixed" if cat and cat.is_fixed else "flexible"] += item.amount

    month_keys = sorted(buckets.keys())[-months:]
    result_months = []
    complete_months = []
    for key in month_keys:
        start, end = _month_bounds(key)
        partial = min_datum > start or max_datum < end
        b = buckets[key]
        s = splits.get(key, {"fixed": 0.0, "flexible": 0.0, "uncategorized": 0.0})
        entry = SavingsCapacityMonth(
            month=key,
            partial=partial,
            income=round(b["income"], 2),
            expenses_total=round(b["expenses_total"], 2),
            expenses_structural=round(b["expenses_structural"], 2),
            incidental=round(b["incidental"], 2),
            fixed=round(s["fixed"], 2),
            flexible=round(s["flexible"], 2),
            uncategorized=round(s["uncategorized"], 2),
            net_raw=round(b["income"] - b["expenses_total"], 2),
            net_structural=round(b["income"] - b["expenses_structural"], 2),
        )
        result_months.append(entry)
        if not partial:
            complete_months.append(entry)

    def trailing(window: int, attr: str) -> float | None:
        if len(complete_months) < window:
            return None
        tail = complete_months[-window:]
        return round(sum(getattr(m, attr) for m in tail) / window, 2)

    return SavingsCapacitySummary(
        months=result_months,
        trailing_3_raw=trailing(3, "net_raw"),
        trailing_3_structural=trailing(3, "net_structural"),
        trailing_6_raw=trailing(6, "net_raw"),
        trailing_6_structural=trailing(6, "net_structural"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/dashboard.py backend/app/schemas.py backend/tests/test_dashboard_insights.py
git commit -m "feat(dashboard): savings-capacity endpoint with structural net and trailing averages"
```

---

### Task 8: Frontend API bindings

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Consumes: all endpoints from Tasks 3-7.
- Produces (used by Tasks 9-12): `OwnAccount`, `BalancePoint`, `SavingsBalance`, `SavingsCapacityMonth`, `SavingsCapacitySummary` interfaces; `getOwnAccounts`, `createOwnAccount`, `updateOwnAccount`, `deleteOwnAccount`, `getBalanceHistory`, `getSavingsBalance`, `getSavingsCapacity`, `setTransactionFlags`, `bulkSetIncidental` functions. `Transaction` and `DashboardSummary` interfaces gain the new fields.

- [ ] **Step 1: Extend existing interfaces**

In `frontend/src/lib/api.ts`, add to `export interface Transaction` (after `has_receipt: boolean;`):

```typescript
	is_internal_transfer: boolean;
	is_incidental: boolean;
```

Add to `export interface DashboardSummary` (find it around line 300, after its last field):

```typescript
	transfers_out: number;
	transfers_in: number;
	transfers_net: number;
```

- [ ] **Step 2: Add new types and functions**

Append to `frontend/src/lib/api.ts`:

```typescript
// --- Own accounts ---

export interface OwnAccount {
	id: number;
	iban: string;
	name: string;
	account_type: 'checking' | 'savings';
	starting_balance: number | null;
	starting_balance_date: string | null;
}

export async function getOwnAccounts(): Promise<OwnAccount[]> {
	return request('/api/own-accounts');
}

export async function createOwnAccount(data: Omit<OwnAccount, 'id'>): Promise<OwnAccount> {
	return request('/api/own-accounts', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data)
	});
}

export async function updateOwnAccount(
	id: number,
	data: Partial<Omit<OwnAccount, 'id'>>
): Promise<OwnAccount> {
	return request(`/api/own-accounts/${id}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data)
	});
}

export async function deleteOwnAccount(id: number): Promise<void> {
	await request(`/api/own-accounts/${id}`, { method: 'DELETE' });
}

// --- Financial insights ---

export interface BalancePoint {
	date: string;
	balance: number;
}

export async function getBalanceHistory(params: {
	date_from?: string;
	date_to?: string;
}): Promise<BalancePoint[]> {
	const qs = new URLSearchParams();
	if (params.date_from) qs.set('date_from', params.date_from);
	if (params.date_to) qs.set('date_to', params.date_to);
	const suffix = qs.toString() ? `?${qs}` : '';
	return request(`/api/dashboard/balance-history${suffix}`);
}

export interface SavingsBalance {
	balance: number;
	is_net_only: boolean;
	account_name: string;
}

export async function getSavingsBalance(): Promise<SavingsBalance | null> {
	return request('/api/dashboard/savings-balance');
}

export interface SavingsCapacityMonth {
	month: string;
	partial: boolean;
	income: number;
	expenses_total: number;
	expenses_structural: number;
	incidental: number;
	fixed: number;
	flexible: number;
	uncategorized: number;
	net_raw: number;
	net_structural: number;
}

export interface SavingsCapacitySummary {
	months: SavingsCapacityMonth[];
	trailing_3_raw: number | null;
	trailing_3_structural: number | null;
	trailing_6_raw: number | null;
	trailing_6_structural: number | null;
	current_month_projection: number | null;
}

export async function getSavingsCapacity(months = 6): Promise<SavingsCapacitySummary> {
	return request(`/api/dashboard/savings-capacity?months=${months}`);
}

export async function setTransactionFlags(
	id: number,
	flags: { is_incidental?: boolean; is_internal_transfer?: boolean }
): Promise<Transaction> {
	return request(`/api/transactions/${id}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(flags)
	});
}

export async function bulkSetIncidental(
	transactionIds: number[],
	isIncidental: boolean
): Promise<{ updated: number }> {
	return request('/api/transactions/bulk-incidental', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ transaction_ids: transactionIds, is_incidental: isIncidental })
	});
}
```

Note: if `api.ts` is already near 800 lines after this, move the new insight types/functions into a new `frontend/src/lib/api-insights.ts` that re-exports through `api.ts` is NOT needed; instead simply create `frontend/src/lib/api-insights.ts` with the new code importing `request`... `request` is not exported. Keep everything in `api.ts` for now and note the file length in the commit message; splitting `api.ts` is a follow-up refactor, not part of this plan.

- [ ] **Step 3: Verify types**

Run: `cd frontend && npm run check`
Expected: 0 errors, 0 warnings

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): API bindings for own accounts, transfers, balance history, savings capacity"
```

---

### Task 9: Settings page for own accounts

**Files:**
- Create: `frontend/src/routes/settings/accounts/+page.svelte`
- Modify: `frontend/src/routes/settings/+page.svelte` (add a link)

**Interfaces:**
- Consumes: `getOwnAccounts`, `createOwnAccount`, `updateOwnAccount`, `deleteOwnAccount` from Task 8.

- [ ] **Step 1: Create the page**

Create `frontend/src/routes/settings/accounts/+page.svelte`. Match the visual language of the existing settings pages (read `frontend/src/routes/settings/security/+page.svelte` first for the card/list styling and reuse its class patterns):

```svelte
<script lang="ts">
	import {
		getOwnAccounts, createOwnAccount, updateOwnAccount, deleteOwnAccount,
		formatEuro, type OwnAccount
	} from '$lib/api';

	let accounts: OwnAccount[] = $state([]);
	let loading = $state(true);
	let error = $state('');

	let newIban = $state('');
	let newName = $state('');
	let newType: 'checking' | 'savings' = $state('checking');
	let newStartingBalance = $state('');
	let newStartingDate = $state('');

	async function load() {
		loading = true;
		error = '';
		try {
			accounts = await getOwnAccounts();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load accounts';
		}
		loading = false;
	}

	$effect(() => { load(); });

	async function addAccount() {
		error = '';
		if (!newIban.trim() || !newName.trim()) {
			error = 'IBAN and name are required';
			return;
		}
		try {
			await createOwnAccount({
				iban: newIban.trim(),
				name: newName.trim(),
				account_type: newType,
				starting_balance: newStartingBalance ? parseFloat(newStartingBalance) : null,
				starting_balance_date: newStartingDate || null
			});
			newIban = '';
			newName = '';
			newStartingBalance = '';
			newStartingDate = '';
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to create account';
		}
	}

	async function saveStartingBalance(account: OwnAccount, balance: string, dateStr: string) {
		error = '';
		try {
			await updateOwnAccount(account.id, {
				starting_balance: balance ? parseFloat(balance) : null,
				starting_balance_date: dateStr || null
			});
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to update account';
		}
	}

	async function removeAccount(account: OwnAccount) {
		if (!confirm(`Remove ${account.name}? Transactions to this account will no longer count as internal transfers.`)) {
			return;
		}
		error = '';
		try {
			await deleteOwnAccount(account.id);
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to delete account';
		}
	}
</script>

<div class="page">
	<h1>Own Accounts</h1>
	<p class="explainer">
		Transactions between these accounts are internal transfers: they are excluded
		from income, expenses, and savings-capacity numbers.
	</p>

	{#if error}
		<div class="error">{error}</div>
	{/if}

	{#if loading}
		<div class="loading">Loading...</div>
	{:else}
		<div class="account-list">
			{#each accounts as account (account.id)}
				<div class="account-card">
					<div class="account-head">
						<div>
							<strong>{account.name}</strong>
							<span class="account-type">{account.account_type}</span>
						</div>
						<button class="danger" onclick={() => removeAccount(account)}>Remove</button>
					</div>
					<div class="iban">{account.iban}</div>
					{#if account.account_type === 'savings'}
						<div class="starting-balance">
							<label>
								Starting balance
								<input
									type="number"
									step="0.01"
									value={account.starting_balance ?? ''}
									onchange={(e) => saveStartingBalance(
										account,
										e.currentTarget.value,
										account.starting_balance_date ?? ''
									)}
								/>
							</label>
							<label>
								as of
								<input
									type="date"
									value={account.starting_balance_date ?? ''}
									onchange={(e) => saveStartingBalance(
										account,
										String(account.starting_balance ?? ''),
										e.currentTarget.value
									)}
								/>
							</label>
							{#if account.starting_balance != null}
								<span class="hint">Currently {formatEuro(account.starting_balance)}</span>
							{:else}
								<span class="hint">Without a starting balance only net transfers are shown</span>
							{/if}
						</div>
					{/if}
				</div>
			{:else}
				<p class="muted">No accounts yet. Add your checking and savings accounts below.</p>
			{/each}
		</div>

		<div class="add-form">
			<h2>Add account</h2>
			<div class="form-row">
				<input placeholder="IBAN" bind:value={newIban} />
				<input placeholder="Name (e.g. Spaarrekening)" bind:value={newName} />
				<select bind:value={newType}>
					<option value="checking">Checking</option>
					<option value="savings">Savings</option>
				</select>
			</div>
			{#if newType === 'savings'}
				<div class="form-row">
					<input type="number" step="0.01" placeholder="Starting balance (optional)" bind:value={newStartingBalance} />
					<input type="date" bind:value={newStartingDate} />
				</div>
			{/if}
			<button class="primary" onclick={addAccount}>Add account</button>
		</div>
	{/if}
</div>

<style>
	.page { max-width: 640px; }
	h1 { margin: 0 0 0.5rem; }
	h2 { font-size: 1.05rem; margin: 0 0 0.75rem; }
	.explainer { color: #666; font-size: 0.9rem; margin-bottom: 1.25rem; }
	.error { background: #fef2f2; color: #dc2626; padding: 0.6rem 0.9rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.9rem; }
	.loading, .muted { color: #999; }
	.account-list { display: flex; flex-direction: column; gap: 0.75rem; margin-bottom: 1.5rem; }
	.account-card { background: white; border-radius: 8px; padding: 1rem 1.25rem; }
	.account-head { display: flex; justify-content: space-between; align-items: center; }
	.account-type { font-size: 0.75rem; color: #666; background: #f0f0f0; border-radius: 4px; padding: 0.1rem 0.4rem; margin-left: 0.5rem; }
	.iban { font-family: monospace; font-size: 0.85rem; color: #444; margin-top: 0.25rem; }
	.starting-balance { display: flex; gap: 0.75rem; align-items: end; flex-wrap: wrap; margin-top: 0.75rem; }
	.starting-balance label { display: flex; flex-direction: column; font-size: 0.75rem; color: #666; gap: 0.2rem; }
	.starting-balance input { padding: 0.35rem 0.5rem; border: 1px solid #ddd; border-radius: 6px; }
	.hint { font-size: 0.75rem; color: #999; }
	.add-form { background: white; border-radius: 8px; padding: 1.25rem; }
	.form-row { display: flex; gap: 0.75rem; margin-bottom: 0.75rem; flex-wrap: wrap; }
	.form-row input, .form-row select { padding: 0.45rem 0.6rem; border: 1px solid #ddd; border-radius: 6px; flex: 1; min-width: 140px; }
	button.primary { background: #2d6a4f; color: white; border: none; border-radius: 6px; padding: 0.5rem 1rem; cursor: pointer; }
	button.danger { background: none; border: 1px solid #dc2626; color: #dc2626; border-radius: 6px; padding: 0.3rem 0.7rem; cursor: pointer; font-size: 0.8rem; }
</style>
```

- [ ] **Step 2: Link it from settings**

In `frontend/src/routes/settings/+page.svelte`, find the existing link to `/settings/security` (or `/settings/sync`) and add an equivalent entry pointing at `/settings/accounts` labeled "Own Accounts" with a short description "Define your own IBANs so transfers between them are excluded from spending".

- [ ] **Step 3: Verify**

Run: `cd frontend && npm run check`
Expected: 0 errors, 0 warnings

Manual smoke test: start the app, open `/settings/accounts`, add both accounts (checking `NL26ASNB8831527878`, plus the savings IBAN), verify a transfer transaction on `/transactions` no longer counts in the dashboard income/expense cards.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/settings/accounts/+page.svelte frontend/src/routes/settings/+page.svelte
git commit -m "feat(frontend): own-accounts settings page"
```

---

### Task 10: Transaction flags in the UI

**Files:**
- Modify: `frontend/src/routes/transactions/+page.svelte`
- Modify: `frontend/src/routes/transactions/[id]/+page.svelte`

**Interfaces:**
- Consumes: `setTransactionFlags` from Task 8; `is_internal_transfer` / `is_incidental` on `Transaction`.

- [ ] **Step 1: List page, transfer badge + incidental toggle**

Read `frontend/src/routes/transactions/+page.svelte` first. In the row template (locate where each transaction's merchant/category is rendered):

1. Add a badge when `tx.is_internal_transfer` is true, next to the category label:

```svelte
{#if tx.is_internal_transfer}
	<span class="badge transfer">transfer</span>
{/if}
{#if tx.is_incidental}
	<span class="badge incidental">incidental</span>
{/if}
```

2. Add an inline toggle action (same placement pattern as the existing inline `CategoryInput`), only for expenses:

```svelte
{#if tx.bedrag < 0 && !tx.is_internal_transfer}
	<button
		class="flag-toggle"
		title={tx.is_incidental ? 'Unmark as incidental (one-off)' : 'Mark as incidental (one-off)'}
		onclick={(e) => { e.stopPropagation(); toggleIncidental(tx); }}
	>{tx.is_incidental ? '★' : '☆'}</button>
{/if}
```

3. Add the handler in the script block, updating the row in place after the API call:

```typescript
async function toggleIncidental(tx: Transaction) {
	const updated = await setTransactionFlags(tx.id, { is_incidental: !tx.is_incidental });
	transactions = transactions.map((t) => (t.id === tx.id ? { ...t, is_incidental: updated.is_incidental } : t));
}
```

Adapt the variable name `transactions` to whatever the page's `$state` list is actually called, and import `setTransactionFlags`. Add badge/button styles consistent with the page's existing badges:

```css
.badge { font-size: 0.65rem; border-radius: 4px; padding: 0.05rem 0.35rem; margin-left: 0.35rem; }
.badge.transfer { background: #eff6ff; color: #2563eb; }
.badge.incidental { background: #fefce8; color: #a16207; }
.flag-toggle { background: none; border: none; cursor: pointer; color: #a16207; font-size: 0.9rem; }
```

- [ ] **Step 2: Detail page, both toggles**

Read `frontend/src/routes/transactions/[id]/+page.svelte`. In its metadata/detail section add a "Flags" block:

```svelte
<div class="flags">
	<label>
		<input
			type="checkbox"
			checked={tx.is_incidental}
			onchange={async () => { tx = { ...tx, ...(await setTransactionFlags(tx.id, { is_incidental: !tx.is_incidental })) }; }}
		/>
		Incidental (one-off, excluded from structural savings capacity)
	</label>
	<label>
		<input
			type="checkbox"
			checked={tx.is_internal_transfer}
			onchange={async () => { tx = { ...tx, ...(await setTransactionFlags(tx.id, { is_internal_transfer: !tx.is_internal_transfer })) }; }}
		/>
		Internal transfer (between own accounts, excluded from income/expenses)
	</label>
</div>
```

Adapt `tx` to the page's actual detail state variable, import `setTransactionFlags`, and style the block like the page's other detail sections. The detail type must include the flags; `TransactionDetail extends Transaction` in `api.ts` so it already does.

Scope note: the `bulkSetIncidental` API binding and its backend endpoint exist (Tasks 4 and 8) but this plan ships only the per-row star toggle. A multi-select bulk UI on the transactions list is deferred to the phases 4-6 plan; the endpoint is already exercised by backend tests.

- [ ] **Step 3: Verify**

Run: `cd frontend && npm run check`
Expected: 0 errors, 0 warnings

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/transactions/+page.svelte "frontend/src/routes/transactions/[id]/+page.svelte"
git commit -m "feat(frontend): transfer badge and incidental toggle on transactions"
```

---

### Task 11: Dashboard, transfers card + balance chart

**Files:**
- Create: `frontend/src/lib/balancePath.ts`
- Create: `frontend/src/lib/balancePath.test.ts`
- Create: `frontend/src/lib/components/BalanceChart.svelte`
- Modify: `frontend/src/routes/+page.svelte`

**Interfaces:**
- Consumes: `getBalanceHistory`, `getSavingsBalance`, `DashboardSummary.transfers_net` from Task 8.
- Produces: `buildBalancePath(points: {date: string; balance: number}[], width: number, height: number): {path: string; min: number; max: number}` pure helper; `<BalanceChart dateFrom={string} dateTo={string} />` self-loading component.

- [ ] **Step 1: Write the failing unit test**

Create `frontend/src/lib/balancePath.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import { buildBalancePath } from './balancePath';

describe('buildBalancePath', () => {
	it('returns empty path for no points', () => {
		expect(buildBalancePath([], 100, 40)).toEqual({ path: '', min: 0, max: 0 });
	});

	it('maps first and last point to the horizontal extremes', () => {
		const points = [
			{ date: '2026-04-01', balance: 0 },
			{ date: '2026-04-15', balance: 50 },
			{ date: '2026-04-30', balance: 100 }
		];
		const { path, min, max } = buildBalancePath(points, 100, 40);
		expect(min).toBe(0);
		expect(max).toBe(100);
		// First point: x=0, y=40 (lowest balance at bottom). Last: x=100, y=0.
		expect(path.startsWith('M 0 40')).toBe(true);
		expect(path.endsWith('L 100 0')).toBe(true);
	});

	it('handles a flat series without dividing by zero', () => {
		const points = [
			{ date: '2026-04-01', balance: 500 },
			{ date: '2026-04-02', balance: 500 }
		];
		const { path } = buildBalancePath(points, 100, 40);
		expect(path).toContain('M 0 20');
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/balancePath.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement the helper**

Create `frontend/src/lib/balancePath.ts`:

```typescript
export interface ChartPoint {
	date: string;
	balance: number;
}

export function buildBalancePath(
	points: ChartPoint[],
	width: number,
	height: number
): { path: string; min: number; max: number } {
	if (points.length === 0) return { path: '', min: 0, max: 0 };

	const balances = points.map((p) => p.balance);
	const min = Math.min(...balances);
	const max = Math.max(...balances);
	const range = max - min;

	const times = points.map((p) => new Date(p.date).getTime());
	const tMin = Math.min(...times);
	const tSpan = Math.max(...times) - tMin;

	const segments = points.map((p, i) => {
		const x = tSpan === 0 ? 0 : ((times[i] - tMin) / tSpan) * width;
		const y = range === 0 ? height / 2 : height - ((p.balance - min) / range) * height;
		return `${i === 0 ? 'M' : 'L'} ${round2(x)} ${round2(y)}`;
	});
	return { path: segments.join(' '), min, max };
}

function round2(n: number): number {
	return Math.round(n * 100) / 100;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/balancePath.test.ts`
Expected: 3 PASS

- [ ] **Step 5: Create the chart component**

Create `frontend/src/lib/components/BalanceChart.svelte`. It follows the app's existing flat visual style (white card, the green `#2d6a4f` accent used by the bar charts):

```svelte
<script lang="ts">
	import { getBalanceHistory, formatEuro, type BalancePoint } from '$lib/api';
	import { buildBalancePath } from '$lib/balancePath';

	let { dateFrom = '', dateTo = '' }: { dateFrom?: string; dateTo?: string } = $props();

	const WIDTH = 600;
	const HEIGHT = 160;

	let points: BalancePoint[] = $state([]);
	let loading = $state(true);
	let error = $state('');

	$effect(() => {
		const params: { date_from?: string; date_to?: string } = {};
		if (dateFrom) params.date_from = dateFrom;
		if (dateTo) params.date_to = dateTo;
		loading = true;
		error = '';
		getBalanceHistory(params)
			.then((p) => { points = p; })
			.catch((e) => { error = e instanceof Error ? e.message : 'Failed to load balance history'; })
			.finally(() => { loading = false; });
	});

	let chart = $derived(buildBalancePath(points, WIDTH, HEIGHT));
	let last = $derived(points.length > 0 ? points[points.length - 1] : null);
</script>

<div class="section">
	<h2>Checking Balance</h2>
	{#if loading}
		<p class="muted">Loading...</p>
	{:else if error}
		<p class="error">{error}</p>
	{:else if points.length < 2}
		<p class="muted">Not enough data for a balance chart yet.</p>
	{:else}
		<div class="chart-meta">
			<span>Low {formatEuro(chart.min)}</span>
			{#if last}<span class="current">Now {formatEuro(last.balance)}</span>{/if}
			<span>High {formatEuro(chart.max)}</span>
		</div>
		<svg viewBox="0 -8 {WIDTH} {HEIGHT + 16}" preserveAspectRatio="none" role="img"
			aria-label="Checking account balance over time, from {formatEuro(chart.min)} to {formatEuro(chart.max)}">
			<path d={chart.path} fill="none" stroke="#2d6a4f" stroke-width="2" vector-effect="non-scaling-stroke" />
		</svg>
		<div class="chart-dates">
			<span>{points[0].date}</span>
			<span>{last?.date}</span>
		</div>
	{/if}
</div>

<style>
	.section { background: white; padding: 1.5rem; border-radius: 8px; }
	h2 { margin: 0 0 1rem; font-size: 1.1rem; }
	.muted { color: #999; font-style: italic; }
	.error { color: #dc2626; font-size: 0.85rem; }
	svg { width: 100%; height: 160px; display: block; }
	.chart-meta { display: flex; justify-content: space-between; font-size: 0.75rem; color: #666; margin-bottom: 0.35rem; }
	.chart-meta .current { font-weight: 600; color: #2d6a4f; }
	.chart-dates { display: flex; justify-content: space-between; font-size: 0.7rem; color: #999; margin-top: 0.25rem; }
</style>
```

- [ ] **Step 6: Wire into the dashboard**

In `frontend/src/routes/+page.svelte`:

1. Import: `import BalanceChart from '$lib/components/BalanceChart.svelte';` and add `getSavingsBalance, type SavingsBalance` to the `$lib/api` import.
2. Add state `let savingsBalance: SavingsBalance | null = $state(null);` and extend `load()`'s `Promise.all` with `getSavingsBalance()`, assigning the extra result.
3. In the `summary-cards` grid, after the Net/burndown card, add:

```svelte
{#if summary.transfers_net !== 0 || savingsBalance}
	<div class="card info">
		<div class="card-value">{formatEuro(summary.transfers_net)}</div>
		<div class="card-label">To savings</div>
		{#if savingsBalance}
			<div class="card-detail">
				{savingsBalance.is_net_only ? 'Net transferred' : 'Balance'}: {formatEuro(savingsBalance.balance)}
			</div>
		{/if}
	</div>
{/if}
```

4. Below the existing `.sections` grid, add the chart (it reloads itself when the date filters change because the props are reactive):

```svelte
<BalanceChart {dateFrom} {dateTo} />
```

- [ ] **Step 7: Verify**

Run: `cd frontend && npm run check && npx vitest run`
Expected: 0 errors/warnings, all tests PASS

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/balancePath.ts frontend/src/lib/balancePath.test.ts frontend/src/lib/components/BalanceChart.svelte frontend/src/routes/+page.svelte
git commit -m "feat(frontend): balance-over-time chart and transfers card on dashboard"
```

---

### Task 12: Dashboard, savings-capacity panel

**Files:**
- Create: `frontend/src/lib/components/SavingsCapacityPanel.svelte`
- Modify: `frontend/src/routes/+page.svelte`

**Interfaces:**
- Consumes: `getSavingsCapacity`, `SavingsCapacitySummary` from Task 8.

- [ ] **Step 1: Create the panel component**

Create `frontend/src/lib/components/SavingsCapacityPanel.svelte`:

```svelte
<script lang="ts">
	import { getSavingsCapacity, formatEuro, type SavingsCapacitySummary } from '$lib/api';

	let data: SavingsCapacitySummary | null = $state(null);
	let loading = $state(true);
	let error = $state('');

	$effect(() => {
		loading = true;
		error = '';
		getSavingsCapacity(6)
			.then((d) => { data = d; })
			.catch((e) => { error = e instanceof Error ? e.message : 'Failed to load savings capacity'; })
			.finally(() => { loading = false; });
	});

	let headline = $derived(data?.trailing_6_structural ?? data?.trailing_3_structural ?? null);
	let headlineWindow = $derived(data?.trailing_6_structural != null ? 6 : 3);
</script>

<div class="section">
	<h2>Savings Capacity</h2>
	{#if loading}
		<p class="muted">Loading...</p>
	{:else if error}
		<p class="error">{error}</p>
	{:else if !data || data.months.length === 0}
		<p class="muted">No data yet. Import transactions first.</p>
	{:else}
		{#if headline != null}
			<div class="headline" class:positive={headline >= 0} class:negative={headline < 0}>
				<span class="headline-value">{formatEuro(headline)}</span>
				<span class="headline-label">structural savings capacity per month ({headlineWindow}-month average)</span>
			</div>
		{:else}
			<p class="muted">
				Fewer than 3 complete months of data; showing months without an average.
			</p>
		{/if}

		<div class="capacity-table">
			<div class="row head">
				<span>Month</span>
				<span class="right">Income</span>
				<span class="right">Structural</span>
				<span class="right">Incidental</span>
				<span class="right">Net</span>
			</div>
			{#each data.months as m (m.month)}
				<div class="row" class:partial={m.partial}>
					<span>{m.month}{m.partial ? ' *' : ''}</span>
					<span class="right income-text">{formatEuro(m.income)}</span>
					<span class="right expense-text">{formatEuro(m.expenses_structural)}</span>
					<span class="right incidental-text">{formatEuro(m.incidental)}</span>
					<span class="right" class:positive={m.net_structural >= 0} class:negative={m.net_structural < 0}>
						{formatEuro(m.net_structural)}
					</span>
				</div>
			{/each}
		</div>
		{#if data.months.some((m) => m.partial)}
			<p class="footnote">* partial month, excluded from averages</p>
		{/if}
		{#if data.trailing_3_structural != null}
			<p class="footnote">
				3-month average {formatEuro(data.trailing_3_structural)} structural
				({formatEuro(data.trailing_3_raw ?? 0)} including incidentals)
			</p>
		{/if}
	{/if}
</div>

<style>
	.section { background: white; padding: 1.5rem; border-radius: 8px; }
	h2 { margin: 0 0 1rem; font-size: 1.1rem; }
	.muted { color: #999; font-style: italic; }
	.error { color: #dc2626; font-size: 0.85rem; }
	.headline { margin-bottom: 1rem; }
	.headline-value { font-size: 1.6rem; font-weight: 700; }
	.headline-label { display: block; font-size: 0.8rem; color: #666; }
	.positive { color: #16a34a; }
	.negative { color: #dc2626; }
	.capacity-table { font-size: 0.85rem; }
	.row { display: grid; grid-template-columns: 1.2fr 1fr 1fr 1fr 1fr; padding: 0.35rem 0; border-bottom: 1px solid #f0f0f0; }
	.row.head { font-weight: 600; font-size: 0.75rem; color: #666; border-bottom: 2px solid #e5e7eb; }
	.row.partial { color: #999; }
	.right { text-align: right; }
	.income-text { color: #16a34a; }
	.expense-text { color: #dc2626; }
	.incidental-text { color: #a16207; }
	.footnote { font-size: 0.7rem; color: #999; margin: 0.4rem 0 0; }
</style>
```

- [ ] **Step 2: Wire into the dashboard**

In `frontend/src/routes/+page.svelte`: import `SavingsCapacityPanel` and render it next to the `BalanceChart` added in Task 11, wrapped in the same two-column grid used by `.sections` (add a second `.sections` div containing both components so they sit side by side on desktop):

```svelte
<div class="sections">
	<BalanceChart {dateFrom} {dateTo} />
	<SavingsCapacityPanel />
</div>
```

(Replace the bare `<BalanceChart {dateFrom} {dateTo} />` line from Task 11 with this grid.)

- [ ] **Step 3: Verify**

Run: `cd frontend && npm run check && npx vitest run`
Expected: clean

Manual smoke test: open the dashboard with real data; check that the headline matches expectations (roughly the 1.000 to 1.200 euro structural capacity computed in the CSV analysis once transfers are flagged and the holiday/IKEA transactions are marked incidental).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/SavingsCapacityPanel.svelte frontend/src/routes/+page.svelte
git commit -m "feat(frontend): savings-capacity panel on dashboard"
```

---

### Task 13: Final verification

**Files:** none new.

- [ ] **Step 1: Full backend suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 2: Full frontend checks**

Run: `cd frontend && npm run check && npx vitest run`
Expected: 0 errors, 0 warnings, all tests PASS

- [ ] **Step 3: End-to-end smoke test with real data**

Start the app. Then:
1. `/settings/accounts`: add checking (`NL26ASNB8831527878`) and savings accounts, set the savings starting balance.
2. `/transactions`: verify "Huur naar spaarpot" rows show the transfer badge.
3. Dashboard: income/expenses cards drop by the transfer amounts; "To savings" card shows; balance chart renders; savings-capacity panel shows monthly nets.
4. Mark the IKEA and holiday-booking transactions incidental (star toggle); watch the structural capacity number rise.

- [ ] **Step 4: Report results**

Report actual command output and screenshots/observations honestly; if anything fails, fix before declaring the plan done. Do not push or open a PR without being asked.
