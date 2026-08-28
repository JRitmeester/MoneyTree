from datetime import date

from sqlalchemy.orm import Session

from app.models import IncidentalLabel

from .conftest import make_transaction


def make_label(db: Session, *, name: str = "Verhuizing") -> IncidentalLabel:
    label = IncidentalLabel(name=name)
    db.add(label)
    db.flush()
    return label


class TestLabelsCrud:
    def test_create_and_list_with_totals(self, client, db: Session):
        resp = client.post("/api/incidental-labels", json={"name": "Vakantie 2026"})
        assert resp.status_code == 200
        label_id = resp.json()["id"]

        a = make_transaction(db, bedrag=-100.0, datum=date(2026, 7, 1))
        b = make_transaction(db, bedrag=-50.0, datum=date(2026, 7, 15))
        for tx in (a, b):
            tx.is_incidental = True
            tx.incidental_label_id = label_id
        db.commit()

        body = client.get("/api/incidental-labels").json()
        assert len(body) == 1
        entry = body[0]
        assert entry["name"] == "Vakantie 2026"
        assert entry["total"] == 150.0
        assert entry["count"] == 2
        assert entry["date_from"] == "2026-07-01"
        assert entry["date_to"] == "2026-07-15"

    def test_create_rejects_duplicate_name(self, client):
        assert client.post("/api/incidental-labels", json={"name": "X"}).status_code == 200
        assert client.post("/api/incidental-labels", json={"name": "X"}).status_code == 409

    def test_create_rejects_blank_name(self, client):
        assert client.post("/api/incidental-labels", json={"name": "  "}).status_code == 422

    def test_rename(self, client, db: Session):
        label = make_label(db)
        db.commit()
        resp = client.patch(f"/api/incidental-labels/{label.id}", json={"name": "Verhuizing 2026"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Verhuizing 2026"

    def test_delete_keeps_transactions_incidental(self, client, db: Session):
        label = make_label(db)
        tx = make_transaction(db, bedrag=-100.0)
        tx.is_incidental = True
        tx.incidental_label_id = label.id
        db.commit()

        assert client.delete(f"/api/incidental-labels/{label.id}").status_code == 200
        db.refresh(tx)
        assert tx.is_incidental is True
        assert tx.incidental_label_id is None

    def test_unknown_label_404(self, client):
        assert client.patch("/api/incidental-labels/999", json={"name": "X"}).status_code == 404
        assert client.delete("/api/incidental-labels/999").status_code == 404


class TestBulkFlags:
    def test_bulk_incidental(self, client, db: Session):
        a = make_transaction(db, bedrag=-100.0)
        b = make_transaction(db, bedrag=-200.0)
        db.commit()
        resp = client.post("/api/transactions/bulk-flags", json={
            "transaction_ids": [a.id, b.id, 99999],
            "is_incidental": True,
        })
        assert resp.status_code == 200
        assert resp.json()["updated"] == 2
        db.refresh(a)
        assert a.is_incidental is True

    def test_bulk_label_implies_incidental(self, client, db: Session):
        label = make_label(db)
        tx = make_transaction(db, bedrag=-100.0)
        db.commit()
        resp = client.post("/api/transactions/bulk-flags", json={
            "transaction_ids": [tx.id],
            "incidental_label_id": label.id,
        })
        assert resp.status_code == 200
        db.refresh(tx)
        assert tx.is_incidental is True
        assert tx.incidental_label_id == label.id

    def test_bulk_unmark_incidental_clears_label(self, client, db: Session):
        label = make_label(db)
        tx = make_transaction(db, bedrag=-100.0)
        tx.is_incidental = True
        tx.incidental_label_id = label.id
        db.commit()
        resp = client.post("/api/transactions/bulk-flags", json={
            "transaction_ids": [tx.id],
            "is_incidental": False,
        })
        assert resp.status_code == 200
        db.refresh(tx)
        assert tx.is_incidental is False
        assert tx.incidental_label_id is None

    def test_bulk_transfer_sets_manual(self, client, db: Session):
        tx = make_transaction(db, bedrag=-500.0)
        db.commit()
        resp = client.post("/api/transactions/bulk-flags", json={
            "transaction_ids": [tx.id],
            "is_internal_transfer": True,
        })
        assert resp.status_code == 200
        db.refresh(tx)
        assert tx.is_internal_transfer is True
        assert tx.is_internal_transfer_manual is True

    def test_bulk_rejects_no_flags(self, client, db: Session):
        tx = make_transaction(db, bedrag=-100.0)
        db.commit()
        resp = client.post("/api/transactions/bulk-flags", json={
            "transaction_ids": [tx.id],
        })
        assert resp.status_code == 422

    def test_bulk_explicit_null_label_clears_label_keeps_incidental(self, client, db: Session):
        label = make_label(db)
        a = make_transaction(db, bedrag=-100.0)
        b = make_transaction(db, bedrag=-200.0)
        for tx in (a, b):
            tx.is_incidental = True
            tx.incidental_label_id = label.id
        db.commit()
        resp = client.post("/api/transactions/bulk-flags", json={
            "transaction_ids": [a.id, b.id],
            "is_incidental": True,
            "incidental_label_id": None,
        })
        assert resp.status_code == 200
        db.refresh(a)
        db.refresh(b)
        assert a.is_incidental is True
        assert a.incidental_label_id is None
        assert b.is_incidental is True
        assert b.incidental_label_id is None

    def test_bulk_rejects_unknown_label(self, client, db: Session):
        tx = make_transaction(db, bedrag=-100.0)
        db.commit()
        resp = client.post("/api/transactions/bulk-flags", json={
            "transaction_ids": [tx.id],
            "incidental_label_id": 999,
        })
        assert resp.status_code == 404


class TestSingleTransactionLabel:
    def test_patch_label_implies_incidental(self, client, db: Session):
        label = make_label(db)
        tx = make_transaction(db, bedrag=-100.0)
        db.commit()
        resp = client.patch(f"/api/transactions/{tx.id}", json={
            "incidental_label_id": label.id,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_incidental"] is True
        assert body["incidental_label_id"] == label.id

    def test_patch_incidental_false_clears_label(self, client, db: Session):
        label = make_label(db)
        tx = make_transaction(db, bedrag=-100.0)
        tx.is_incidental = True
        tx.incidental_label_id = label.id
        db.commit()
        resp = client.patch(f"/api/transactions/{tx.id}", json={"is_incidental": False})
        assert resp.status_code == 200
        db.refresh(tx)
        assert tx.incidental_label_id is None

    def test_patch_incidental_false_wins_over_label(self, client, db: Session):
        label = make_label(db)
        tx = make_transaction(db, bedrag=-100.0)
        db.commit()
        resp = client.patch(f"/api/transactions/{tx.id}", json={
            "is_incidental": False,
            "incidental_label_id": label.id,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_incidental"] is False
        assert body["incidental_label_id"] is None


class TestLabelFilter:
    def test_transactions_filter_by_label(self, client, db: Session):
        label = IncidentalLabel(name="Vakantie")
        db.add(label)
        db.flush()
        labeled = make_transaction(db, bedrag=-50.0)
        labeled.is_incidental = True
        labeled.incidental_label_id = label.id
        unlabeled = make_transaction(db, bedrag=-30.0)
        unlabeled.is_incidental = True
        make_transaction(db, bedrag=-10.0)
        db.commit()

        body = client.get(f"/api/transactions?incidental_label_id={label.id}").json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == labeled.id

    def test_unknown_label_returns_empty(self, client, db: Session):
        make_transaction(db, bedrag=-10.0)
        db.commit()
        body = client.get("/api/transactions?incidental_label_id=9999").json()
        assert body["total"] == 0
