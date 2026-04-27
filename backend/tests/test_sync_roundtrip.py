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


def _fresh_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_full_roundtrip_preserves_state(db):
    """Export a fully populated source DB and import into a fresh DB.

    The destination must have identical row counts and relationships.
    """
    parent = make_category(db, name="Living")
    child = Category(name="Groceries", parent_id=parent.id, category_type="expense")
    db.add(child)
    db.flush()

    db.add(CategoryMapping(bank_category="Boodschappen", category_id=child.id))
    db.add(BudgetTemplate(category_id=child.id, amount=350.0))

    budget = Budget(start_date=date(2026, 4, 1), end_date=date(2026, 5, 1))
    db.add(budget)
    db.flush()
    db.add(BudgetLine(budget_id=budget.id, category_id=child.id, amount=350.0))

    expense = make_transaction(db, bedrag=-30.0, category_id=child.id)
    income = make_transaction(db, bedrag=30.0, category_id=child.id)
    db.add(TransactionOffset(expense_transaction_id=expense.id, income_transaction_id=income.id))
    db.commit()

    export = build_export(db, since=None)

    dest = _fresh_session()
    commit_import(dest, export, update_duplicates=False)

    cats = dest.execute(select(Category)).scalars().all()
    assert {c.name for c in cats} == {"Living", "Groceries"}
    grocery = next(c for c in cats if c.name == "Groceries")
    assert grocery.parent.name == "Living"

    assert len(dest.execute(select(CategoryMapping)).scalars().all()) == 1
    assert len(dest.execute(select(Budget)).scalars().all()) == 1
    assert dest.execute(select(BudgetLine)).scalars().one().amount == 350.0
    assert len(dest.execute(select(BudgetTemplate)).scalars().all()) == 1
    assert len(dest.execute(select(Transaction)).scalars().all()) == 2
    assert dest.execute(select(TransactionOffset)).scalars().one() is not None


def test_idempotent_double_import(db):
    """Importing the same export twice must not create duplicate rows."""
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.add(BudgetTemplate(category_id=cat.id, amount=200.0))
    budget = Budget(start_date=date(2026, 4, 1), end_date=date(2026, 5, 1))
    db.add(budget)
    db.flush()
    db.add(BudgetLine(budget_id=budget.id, category_id=cat.id, amount=200.0))
    db.commit()

    export = build_export(db, since=None)

    dest = _fresh_session()
    commit_import(dest, export, update_duplicates=False)
    commit_import(dest, export, update_duplicates=False)

    assert len(dest.execute(select(Category)).scalars().all()) == 1
    assert len(dest.execute(select(Budget)).scalars().all()) == 1
    assert len(dest.execute(select(BudgetLine)).scalars().all()) == 1
    assert len(dest.execute(select(Transaction)).scalars().all()) == 1
