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
    old_tx.updated_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
    new_tx = make_transaction(db, category_id=cat.id)
    new_tx.created_at = datetime(2026, 4, 15, tzinfo=timezone.utc)
    new_tx.updated_at = datetime(2026, 4, 15, tzinfo=timezone.utc)
    db.commit()

    export = build_export(db, since=date(2026, 4, 1))

    hashes = {t.import_hash for t in export.transactions}
    assert new_tx.import_hash in hashes
    assert old_tx.import_hash not in hashes


def test_build_export_includes_edited_transaction_via_updated_at(db):
    """A transaction created before the cutoff but edited during the outage
    should be included in the export when filtering by `since`."""
    cat = make_category(db, name="Groceries")
    edited_tx = make_transaction(db, category_id=cat.id)
    # Created before outage, edited during outage
    edited_tx.created_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
    edited_tx.updated_at = datetime(2026, 4, 15, tzinfo=timezone.utc)
    db.commit()

    export = build_export(db, since=date(2026, 4, 1))
    hashes = {t.import_hash for t in export.transactions}
    assert edited_tx.import_hash in hashes
