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
