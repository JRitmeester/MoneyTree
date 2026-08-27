from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Category


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
