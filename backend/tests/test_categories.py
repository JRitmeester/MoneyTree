from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Budget, BudgetLine, BudgetTemplate, Category, CategoryMapping, LineItem, Receipt

from .conftest import make_category, make_transaction


# --- Task 1: PATCH must not reset flags ---


def test_patch_rename_only_preserves_is_fixed_and_type(client: TestClient, db: Session):
    cat = Category(name="Rent", category_type="income", is_fixed=True)
    db.add(cat)
    db.commit()
    db.refresh(cat)

    resp = client.patch(f"/api/categories/{cat.id}", json={"name": "Housing"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Housing"
    assert body["is_fixed"] is True
    assert body["category_type"] == "income"


def test_patch_type_toggle_only_preserves_is_fixed(client: TestClient, db: Session):
    cat = Category(name="Subscriptions", category_type="expense", is_fixed=True)
    db.add(cat)
    db.commit()
    db.refresh(cat)

    resp = client.patch(f"/api/categories/{cat.id}", json={"category_type": "income"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["category_type"] == "income"
    assert body["is_fixed"] is True
    assert body["name"] == "Subscriptions"


def test_patch_with_explicit_is_fixed_still_applies(client: TestClient, db: Session):
    cat = Category(name="Groceries", category_type="expense", is_fixed=False)
    db.add(cat)
    db.commit()
    db.refresh(cat)

    resp = client.patch(f"/api/categories/{cat.id}", json={"is_fixed": True})

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_fixed"] is True
    assert body["category_type"] == "expense"
    assert body["name"] == "Groceries"


def test_patch_rename_still_records_rename_event(client: TestClient, db: Session):
    cat = Category(name="OldName", category_type="expense", is_fixed=False)
    db.add(cat)
    db.commit()
    db.refresh(cat)

    resp = client.patch(f"/api/categories/{cat.id}", json={"name": "NewName"})

    assert resp.status_code == 200
    assert resp.json()["name"] == "NewName"


# --- Task 2: safe category delete ---


def test_delete_blocked_by_referencing_transaction(client: TestClient, db: Session):
    cat = make_category(db, name="Referenced")
    make_transaction(db, category_id=cat.id)
    db.commit()

    resp = client.delete(f"/api/categories/{cat.id}")

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "1 transaction" in detail


def test_delete_unreferenced_leaf_category_succeeds(client: TestClient, db: Session):
    cat = make_category(db, name="Unused")
    db.commit()

    resp = client.delete(f"/api/categories/{cat.id}")

    assert resp.status_code == 200


def test_delete_blocked_by_children(client: TestClient, db: Session):
    parent = make_category(db, name="Parent")
    db.commit()
    child = Category(name="Child", parent_id=parent.id)
    db.add(child)
    db.commit()

    resp = client.delete(f"/api/categories/{parent.id}")

    assert resp.status_code == 409


def test_delete_blocked_by_line_item(client: TestClient, db: Session):
    cat = make_category(db, name="LineItemCat")
    receipt = Receipt(transaction_id=None)
    db.add(receipt)
    db.flush()
    line_item = LineItem(receipt_id=receipt.id, description="Item", amount=5.0, category_id=cat.id)
    db.add(line_item)
    db.commit()

    resp = client.delete(f"/api/categories/{cat.id}")

    assert resp.status_code == 409
    assert "1 line item" in resp.json()["detail"]


def test_delete_blocked_by_budget_line(client: TestClient, db: Session):
    cat = make_category(db, name="BudgetLineCat")
    budget = Budget(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
    db.add(budget)
    db.flush()
    budget_line = BudgetLine(budget_id=budget.id, category_id=cat.id, amount=100.0)
    db.add(budget_line)
    db.commit()

    resp = client.delete(f"/api/categories/{cat.id}")

    assert resp.status_code == 409
    assert "1 budget line" in resp.json()["detail"]


def test_delete_blocked_by_budget_template(client: TestClient, db: Session):
    cat = make_category(db, name="TemplateCat")
    template = BudgetTemplate(category_id=cat.id, amount=50.0)
    db.add(template)
    db.commit()

    resp = client.delete(f"/api/categories/{cat.id}")

    assert resp.status_code == 409
    assert "1 budget template" in resp.json()["detail"]


def test_delete_blocked_by_category_mapping(client: TestClient, db: Session):
    cat = make_category(db, name="MappedCat")
    mapping = CategoryMapping(bank_category="SUPERMARKT", category_id=cat.id)
    db.add(mapping)
    db.commit()

    resp = client.delete(f"/api/categories/{cat.id}")

    assert resp.status_code == 409
    assert "1 category mapping" in resp.json()["detail"]


def test_delete_message_lists_multiple_reference_kinds(client: TestClient, db: Session):
    cat = make_category(db, name="MultiRef")
    make_transaction(db, category_id=cat.id)
    budget = Budget(start_date=date(2026, 2, 1), end_date=date(2026, 2, 28))
    db.add(budget)
    db.flush()
    db.add(BudgetLine(budget_id=budget.id, category_id=cat.id, amount=25.0))
    db.commit()

    resp = client.delete(f"/api/categories/{cat.id}")

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "transaction" in detail
    assert "budget line" in detail
