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
