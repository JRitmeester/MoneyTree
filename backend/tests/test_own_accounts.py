from datetime import date

from sqlalchemy.orm import Session

from app.models import OwnAccount, Transaction

from .conftest import make_transaction


class TestOwnAccountModel:
    def test_own_account_persists_all_fields(self, db: Session):
        acc = OwnAccount(
            iban="NL26ASNB8831527878",
            name="Betaalrekening",
            account_type="checking",
        )
        savings = OwnAccount(
            iban="NL00ASNB0000000002",
            name="Spaarrekening",
            account_type="savings",
            starting_balance=5000.0,
            starting_balance_date=date(2026, 4, 1),
        )
        db.add_all([acc, savings])
        db.flush()

        loaded = db.get(OwnAccount, savings.id)
        assert loaded.iban == "NL00ASNB0000000002"
        assert loaded.account_type == "savings"
        assert loaded.starting_balance == 5000.0
        assert loaded.starting_balance_date == date(2026, 4, 1)
        assert acc.starting_balance is None

    def test_transaction_flags_default_false(self, db: Session):
        tx = make_transaction(db)
        assert tx.is_internal_transfer is False
        assert tx.is_internal_transfer_manual is False
        assert tx.is_incidental is False


class TestOwnAccountsApi:
    def test_create_and_list(self, client, db: Session):
        resp = client.post("/api/own-accounts", json={
            "iban": "nl26 asnb 8831 5278 78",
            "name": "Betaalrekening",
            "account_type": "checking",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["iban"] == "NL26ASNB8831527878"  # normalized on create

        resp = client.get("/api/own-accounts")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_create_rejects_bad_account_type(self, client):
        resp = client.post("/api/own-accounts", json={
            "iban": "NL26ASNB8831527878",
            "name": "X",
            "account_type": "bitcoin",
        })
        assert resp.status_code == 422

    def test_create_rejects_duplicate_iban(self, client):
        payload = {"iban": "NL26ASNB8831527878", "name": "A", "account_type": "checking"}
        assert client.post("/api/own-accounts", json=payload).status_code == 200
        resp = client.post("/api/own-accounts", json=payload)
        assert resp.status_code == 409

    def test_create_triggers_backfill(self, client, db: Session):
        tx = make_transaction(db, bedrag=-500.0, tegenrekening="NL00ASNB0000000002")
        db.commit()
        resp = client.post("/api/own-accounts", json={
            "iban": "NL00ASNB0000000002",
            "name": "Spaarrekening",
            "account_type": "savings",
        })
        assert resp.status_code == 200
        db.refresh(tx)
        assert tx.is_internal_transfer is True

    def test_delete_triggers_backfill(self, client, db: Session):
        tx = make_transaction(db, bedrag=-500.0, tegenrekening="NL00ASNB0000000002")
        db.commit()
        created = client.post("/api/own-accounts", json={
            "iban": "NL00ASNB0000000002", "name": "S", "account_type": "savings",
        }).json()
        resp = client.delete(f"/api/own-accounts/{created['id']}")
        assert resp.status_code == 200
        db.refresh(tx)
        assert tx.is_internal_transfer is False

    def test_patch_updates_starting_balance(self, client):
        created = client.post("/api/own-accounts", json={
            "iban": "NL00ASNB0000000002", "name": "S", "account_type": "savings",
        }).json()
        resp = client.patch(f"/api/own-accounts/{created['id']}", json={
            "starting_balance": 2500.0,
            "starting_balance_date": "2026-04-01",
        })
        assert resp.status_code == 200
        assert resp.json()["starting_balance"] == 2500.0

    def test_patch_unknown_id_404(self, client):
        assert client.patch("/api/own-accounts/999", json={"name": "X"}).status_code == 404
