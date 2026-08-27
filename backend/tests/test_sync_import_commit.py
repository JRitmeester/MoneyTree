from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.models import (
    Base, Budget, BudgetLine, BudgetTemplate, Category,
    CategoryMapping, IncidentalLabel, OwnAccount, Transaction, TransactionOffset,
)
from app.services.sync_export import build_export
from app.services.sync_import import commit_import, preview_import
from app.sync_schemas import ExportFile
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


def test_commit_imports_flags_labels_and_own_accounts_into_empty_db(db):
    cat = make_category(db, name="Groceries")
    label = IncidentalLabel(name="Summer Holiday")
    db.add(label); db.flush()
    tx = make_transaction(db, category_id=cat.id)
    tx.is_internal_transfer = True
    tx.is_incidental = True
    tx.incidental_label_id = label.id
    db.add(OwnAccount(iban="NL00BANK0000000001", name="Checking", account_type="checking"))
    db.commit()

    export = build_export(db, since=None)
    dest = _fresh_session()
    commit_import(dest, export, update_duplicates=False)

    dest_tx = dest.execute(select(Transaction)).scalars().one()
    assert dest_tx.is_internal_transfer is True
    assert dest_tx.is_incidental is True
    dest_label = dest.execute(select(IncidentalLabel)).scalars().one()
    assert dest_label.name == "Summer Holiday"
    assert dest_tx.incidental_label_id == dest_label.id
    dest_account = dest.execute(select(OwnAccount)).scalars().one()
    assert dest_account.iban == "NL00BANK0000000001"


def test_commit_import_creates_missing_own_account_but_keeps_existing_iban(db):
    make_category(db, name="Groceries")
    db.add(OwnAccount(iban="NL00BANK0000000001", name="Source Checking", account_type="checking"))
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh_session()
    dest.add(OwnAccount(iban="NL00BANK0000000001", name="Dest Checking", account_type="checking"))
    dest.commit()

    preview = commit_import(dest, export, update_duplicates=False)

    accounts = dest.execute(select(OwnAccount)).scalars().all()
    assert len(accounts) == 1
    assert accounts[0].name == "Dest Checking"
    assert any(c.code == "own_account_conflict" for c in preview.soft_conflicts)


def test_commit_imports_legacy_export_without_new_fields(db):
    """Export files predating the flags/labels/own-accounts fields must still import cleanly."""
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.commit()
    export = build_export(db, since=None)

    payload = export.model_dump()
    payload["format_version"] = 1
    for et in payload["transactions"]:
        del et["is_internal_transfer"]
        del et["is_internal_transfer_manual"]
        del et["is_incidental"]
        del et["incidental_label"]
    del payload["incidental_labels"]
    del payload["own_accounts"]
    legacy_export = ExportFile.model_validate(payload)

    dest = _fresh_session()
    commit_import(dest, legacy_export, update_duplicates=False)

    dest_tx = dest.execute(select(Transaction)).scalars().one()
    assert dest_tx.is_internal_transfer is False
    assert dest_tx.is_internal_transfer_manual is False
    assert dest_tx.is_incidental is False
    assert dest_tx.incidental_label_id is None


def test_legacy_v1_import_does_not_flood_transaction_flags_conflicts(db):
    """A format_version=1 export must never apply flags or count
    transaction_flags_conflict entries, even when the destination row is
    already curated with non-default flags."""
    cat = make_category(db, name="Groceries")
    tx = make_transaction(db, category_id=cat.id)
    db.commit()
    export = build_export(db, since=None)

    payload = export.model_dump()
    payload["format_version"] = 1
    for et in payload["transactions"]:
        del et["is_internal_transfer"]
        del et["is_internal_transfer_manual"]
        del et["is_incidental"]
        del et["incidental_label"]
    del payload["incidental_labels"]
    del payload["own_accounts"]
    legacy_export = ExportFile.model_validate(payload)

    # Destination already curated this transaction locally (non-default flags)
    tx.is_incidental = True
    db.commit()

    preview = commit_import(db, legacy_export, update_duplicates=False)
    db.refresh(tx)

    assert tx.is_incidental is True
    assert tx.is_internal_transfer is False
    assert not any(c.code == "transaction_flags_conflict" for c in preview.soft_conflicts)


def test_commit_does_not_overwrite_existing_transaction_curated_flags(db):
    cat = make_category(db, name="Groceries")
    tx = make_transaction(db, category_id=cat.id)
    db.commit()
    export = build_export(db, since=None)
    et = next(e for e in export.transactions if e.import_hash == tx.import_hash)
    et.is_internal_transfer = True

    # Destination already curated this transaction locally (non-default flags)
    tx.is_incidental = True
    db.commit()

    preview = commit_import(db, export, update_duplicates=True)
    db.refresh(tx)

    assert tx.is_internal_transfer is False
    assert tx.is_incidental is True
    assert any(c.code == "transaction_flags_conflict" for c in preview.soft_conflicts)


def test_commit_applies_flags_to_existing_transaction_with_default_flags(db):
    cat = make_category(db, name="Groceries")
    tx = make_transaction(db, category_id=cat.id)
    db.commit()
    export = build_export(db, since=None)
    et = next(e for e in export.transactions if e.import_hash == tx.import_hash)
    et.is_internal_transfer = True
    et.is_incidental = True

    commit_import(db, export, update_duplicates=False)
    db.refresh(tx)

    assert tx.is_internal_transfer is True
    assert tx.is_incidental is True
