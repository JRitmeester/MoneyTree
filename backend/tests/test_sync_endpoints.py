import json
from datetime import date, datetime, timezone

from app.sync_schemas import ExportFile
from tests.conftest import make_category, make_transaction


def test_export_endpoint_returns_json(client, db):
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.commit()

    resp = client.get("/api/sync/export")
    assert resp.status_code == 200
    body = resp.json()
    assert body["format_version"] == 3
    assert any(c["name"] == "Groceries" for c in body["categories"])
    assert len(body["transactions"]) == 1


def test_export_endpoint_accepts_since(client, db):
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.commit()

    resp = client.get("/api/sync/export?since=2030-01-01")
    assert resp.status_code == 200
    assert resp.json()["transactions"] == []


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
