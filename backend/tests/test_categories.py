import json
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Budget, BudgetLine, BudgetTemplate, Category, CategoryMapping, LineItem, Receipt,
    SyncEvent,
)

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


# --- Task 1 (categories-offsets): category merge ---


def test_merge_dry_run_returns_counts_without_mutating(client: TestClient, db: Session):
    source = make_category(db, name="Source")
    target = make_category(db, name="Target")
    tx = make_transaction(db, category_id=source.id)
    db.commit()

    resp = client.post(f"/api/categories/{source.id}/merge-into/{target.id}?dry_run=true")

    assert resp.status_code == 200
    body = resp.json()
    assert body["transactions"] == 1
    assert body["line_items"] == 0
    assert body["budget_lines"] == 0
    assert body["budget_templates"] == 0
    assert body["category_mappings"] == 0
    assert body["children"] == 0

    db.refresh(tx)
    assert tx.category_id == source.id
    assert db.get(Category, source.id) is not None
    assert db.execute(select(SyncEvent)).scalars().all() == []


def test_merge_repoints_all_references_and_sums_budget_lines(client: TestClient, db: Session):
    source = make_category(db, name="Source")
    target = make_category(db, name="Target")
    tx = make_transaction(db, category_id=source.id)

    receipt = Receipt(transaction_id=None)
    db.add(receipt)
    db.flush()
    line_item = LineItem(receipt_id=receipt.id, description="Item", amount=5.0, category_id=source.id)
    db.add(line_item)

    mapping = CategoryMapping(bank_category="BANKCAT", category_id=source.id)
    db.add(mapping)

    budget = Budget(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))
    db.add(budget)
    db.flush()
    source_line = BudgetLine(budget_id=budget.id, category_id=source.id, amount=50.0)
    target_line = BudgetLine(budget_id=budget.id, category_id=target.id, amount=30.0)
    db.add(source_line)
    db.add(target_line)

    source_template = BudgetTemplate(category_id=source.id, amount=100.0)
    target_template = BudgetTemplate(category_id=target.id, amount=20.0)
    db.add(source_template)
    db.add(target_template)

    child = Category(name="Child", parent_id=source.id)
    db.add(child)
    db.commit()

    resp = client.post(f"/api/categories/{source.id}/merge-into/{target.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["transactions"] == 1
    assert body["line_items"] == 1
    assert body["budget_lines"] == 1
    assert body["budget_templates"] == 1
    assert body["category_mappings"] == 1
    assert body["children"] == 1

    db.refresh(tx)
    assert tx.category_id == target.id
    db.refresh(line_item)
    assert line_item.category_id == target.id
    db.refresh(mapping)
    assert mapping.category_id == target.id
    db.refresh(child)
    assert child.parent_id == target.id

    remaining_lines = db.execute(
        select(BudgetLine).where(BudgetLine.budget_id == budget.id)
    ).scalars().all()
    assert len(remaining_lines) == 1
    assert remaining_lines[0].category_id == target.id
    assert remaining_lines[0].amount == 80.0

    remaining_templates = db.execute(select(BudgetTemplate)).scalars().all()
    assert len(remaining_templates) == 1
    assert remaining_templates[0].category_id == target.id
    assert remaining_templates[0].amount == 120.0

    assert db.get(Category, source.id) is None


def test_merge_repoints_budget_line_when_no_clash(client: TestClient, db: Session):
    source = make_category(db, name="Source")
    target = make_category(db, name="Target")
    budget = Budget(start_date=date(2026, 3, 1), end_date=date(2026, 3, 31))
    db.add(budget)
    db.flush()
    line = BudgetLine(budget_id=budget.id, category_id=source.id, amount=40.0)
    db.add(line)
    db.commit()

    resp = client.post(f"/api/categories/{source.id}/merge-into/{target.id}")

    assert resp.status_code == 200
    db.refresh(line)
    assert line.category_id == target.id
    assert line.amount == 40.0


def test_merge_source_equals_target_rejected(client: TestClient, db: Session):
    cat = make_category(db, name="Solo")
    db.commit()

    resp = client.post(f"/api/categories/{cat.id}/merge-into/{cat.id}")

    assert resp.status_code == 400


def test_merge_into_descendant_rejected(client: TestClient, db: Session):
    parent = make_category(db, name="Parent")
    db.commit()
    child = Category(name="Child", parent_id=parent.id)
    db.add(child)
    db.commit()
    db.refresh(child)

    resp = client.post(f"/api/categories/{parent.id}/merge-into/{child.id}")

    assert resp.status_code == 400


def test_merge_source_not_found(client: TestClient, db: Session):
    target = make_category(db, name="OnlyTarget")
    db.commit()

    resp = client.post(f"/api/categories/9999/merge-into/{target.id}")

    assert resp.status_code == 404


def test_merge_records_sync_event(client: TestClient, db: Session):
    source = make_category(db, name="EventSource")
    target = make_category(db, name="EventTarget")
    db.commit()

    resp = client.post(f"/api/categories/{source.id}/merge-into/{target.id}")

    assert resp.status_code == 200
    events = db.execute(select(SyncEvent)).scalars().all()
    assert len(events) == 1
    assert events[0].event_type == "category.merge"
    payload = json.loads(events[0].payload_json)
    assert payload["source_name"] == "EventSource"
    assert payload["target_name"] == "EventTarget"
    assert payload["source_path"] == "EventSource"
    assert payload["target_path"] == "EventTarget"


# --- Task 2: per-parent category names ---


def test_create_allows_same_name_under_different_parents(client: TestClient, db: Session):
    parent_a = make_category(db, name="ParentA")
    parent_b = make_category(db, name="ParentB")
    db.commit()

    resp_a = client.post("/api/categories", json={"name": "Overig", "parent_id": parent_a.id})
    resp_b = client.post("/api/categories", json={"name": "Overig", "parent_id": parent_b.id})

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["id"] != resp_b.json()["id"]


def test_create_rejects_duplicate_name_under_same_parent(client: TestClient, db: Session):
    parent = make_category(db, name="Parent")
    db.commit()
    client.post("/api/categories", json={"name": "Child", "parent_id": parent.id})

    resp = client.post("/api/categories", json={"name": "Child", "parent_id": parent.id})

    assert resp.status_code == 409
    assert resp.json()["detail"] == 'A category named "Child" already exists under "Parent"'


def test_create_rejects_duplicate_name_at_top_level(client: TestClient, db: Session):
    make_category(db, name="Root")
    db.commit()

    resp = client.post("/api/categories", json={"name": "Root"})

    assert resp.status_code == 409
    assert resp.json()["detail"] == 'A category named "Root" already exists at the top level'


def test_rename_rejects_collision_with_sibling(client: TestClient, db: Session):
    parent = make_category(db, name="Parent")
    db.commit()
    child_a = Category(name="Alpha", parent_id=parent.id)
    child_b = Category(name="Beta", parent_id=parent.id)
    db.add_all([child_a, child_b])
    db.commit()
    db.refresh(child_b)

    resp = client.patch(f"/api/categories/{child_b.id}", json={"name": "Alpha"})

    assert resp.status_code == 409
    assert resp.json()["detail"] == 'A category named "Alpha" already exists under "Parent"'


def test_rename_allows_same_name_under_different_parents(client: TestClient, db: Session):
    parent_a = make_category(db, name="ParentA")
    parent_b = make_category(db, name="ParentB")
    db.commit()
    child_a = Category(name="Alpha", parent_id=parent_a.id)
    child_b = Category(name="Beta", parent_id=parent_b.id)
    db.add_all([child_a, child_b])
    db.commit()
    db.refresh(child_b)

    resp = client.patch(f"/api/categories/{child_b.id}", json={"name": "Alpha"})

    assert resp.status_code == 200
    assert resp.json()["name"] == "Alpha"


def test_move_rejects_collision_with_sibling_under_new_parent(client: TestClient, db: Session):
    parent_a = make_category(db, name="ParentA")
    parent_b = make_category(db, name="ParentB")
    db.commit()
    existing = Category(name="Shared", parent_id=parent_b.id)
    moving = Category(name="Shared", parent_id=parent_a.id)
    db.add_all([existing, moving])
    db.commit()
    db.refresh(moving)

    resp = client.patch(f"/api/categories/{moving.id}", json={"parent_id": parent_b.id})

    assert resp.status_code == 409
    assert resp.json()["detail"] == 'A category named "Shared" already exists under "ParentB"'


def test_rename_unchanged_name_does_not_self_collide(client: TestClient, db: Session):
    parent = make_category(db, name="Parent")
    db.commit()
    child = Category(name="Alpha", parent_id=parent.id)
    db.add(child)
    db.commit()
    db.refresh(child)

    resp = client.patch(f"/api/categories/{child.id}", json={"is_fixed": True})

    assert resp.status_code == 200
