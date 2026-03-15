from sqlalchemy.orm import Session

from app.models import Receipt

from .conftest import make_category, make_transaction


class TestCategorizeSelected:
    """Tests for POST /api/uncategorized/categorize-selected."""

    def test_rejects_empty_transaction_ids(self, client):
        response = client.post(
            "/api/uncategorized/categorize-selected",
            json={"transaction_ids": [], "category_id": 1},
        )
        assert response.status_code == 400
        assert "No transaction IDs" in response.json()["detail"]

    def test_rejects_nonexistent_category(self, client):
        response = client.post(
            "/api/uncategorized/categorize-selected",
            json={"transaction_ids": [1], "category_id": 9999},
        )
        assert response.status_code == 404
        assert "Category not found" in response.json()["detail"]

    def test_categorizes_selected_transactions(self, client, db: Session):
        cat = make_category(db, name="Food")
        tx1 = make_transaction(db, categorie="Boodschappen")
        tx2 = make_transaction(db, categorie="Boodschappen")
        db.commit()

        response = client.post(
            "/api/uncategorized/categorize-selected",
            json={"transaction_ids": [tx1.id, tx2.id], "category_id": cat.id},
        )
        assert response.status_code == 200
        assert response.json() == {"updated": 2}

        db.refresh(tx1)
        db.refresh(tx2)
        assert tx1.category_id == cat.id
        assert tx2.category_id == cat.id

    def test_only_updates_requested_ids(self, client, db: Session):
        cat = make_category(db, name="Food")
        tx1 = make_transaction(db, categorie="Boodschappen")
        tx2 = make_transaction(db, categorie="Boodschappen")
        db.commit()

        response = client.post(
            "/api/uncategorized/categorize-selected",
            json={"transaction_ids": [tx1.id], "category_id": cat.id},
        )
        assert response.status_code == 200
        assert response.json() == {"updated": 1}

        db.refresh(tx1)
        db.refresh(tx2)
        assert tx1.category_id == cat.id
        assert tx2.category_id is None

    def test_skips_already_categorized_transactions(self, client, db: Session):
        existing_cat = make_category(db, name="Existing")
        new_cat = make_category(db, name="New")
        tx1 = make_transaction(db, categorie="Boodschappen", category_id=existing_cat.id)
        tx2 = make_transaction(db, categorie="Boodschappen")
        db.commit()

        response = client.post(
            "/api/uncategorized/categorize-selected",
            json={"transaction_ids": [tx1.id, tx2.id], "category_id": new_cat.id},
        )
        assert response.status_code == 200
        assert response.json() == {"updated": 1}

        db.refresh(tx1)
        db.refresh(tx2)
        assert tx1.category_id == existing_cat.id  # unchanged
        assert tx2.category_id == new_cat.id

    def test_skips_income_transactions(self, client, db: Session):
        cat = make_category(db, name="Food")
        expense = make_transaction(db, bedrag=-25.0)
        income = make_transaction(db, bedrag=100.0)
        db.commit()

        response = client.post(
            "/api/uncategorized/categorize-selected",
            json={"transaction_ids": [expense.id, income.id], "category_id": cat.id},
        )
        assert response.status_code == 200
        assert response.json() == {"updated": 1}

        db.refresh(expense)
        db.refresh(income)
        assert expense.category_id == cat.id
        assert income.category_id is None

    def test_skips_transactions_with_receipt(self, client, db: Session):
        cat = make_category(db, name="Food")
        tx_with_receipt = make_transaction(db, categorie="Boodschappen")
        tx_without_receipt = make_transaction(db, categorie="Boodschappen")
        receipt = Receipt(transaction_id=tx_with_receipt.id)
        db.add(receipt)
        db.commit()

        response = client.post(
            "/api/uncategorized/categorize-selected",
            json={
                "transaction_ids": [tx_with_receipt.id, tx_without_receipt.id],
                "category_id": cat.id,
            },
        )
        assert response.status_code == 200
        assert response.json() == {"updated": 1}

        db.refresh(tx_with_receipt)
        db.refresh(tx_without_receipt)
        assert tx_with_receipt.category_id is None
        assert tx_without_receipt.category_id == cat.id

    def test_handles_nonexistent_transaction_ids(self, client, db: Session):
        cat = make_category(db, name="Food")
        tx = make_transaction(db, categorie="Boodschappen")
        db.commit()

        response = client.post(
            "/api/uncategorized/categorize-selected",
            json={"transaction_ids": [tx.id, 99999], "category_id": cat.id},
        )
        assert response.status_code == 200
        assert response.json() == {"updated": 1}

    def test_works_across_bank_categories(self, client, db: Session):
        cat = make_category(db, name="Food")
        tx1 = make_transaction(db, categorie="Boodschappen")
        tx2 = make_transaction(db, categorie="Horeca")
        db.commit()

        response = client.post(
            "/api/uncategorized/categorize-selected",
            json={"transaction_ids": [tx1.id, tx2.id], "category_id": cat.id},
        )
        assert response.status_code == 200
        assert response.json() == {"updated": 2}


class TestListUncategorized:
    """Tests for GET /api/uncategorized."""

    def test_returns_empty_when_no_uncategorized(self, client, db: Session):
        db.commit()
        response = client.get("/api/uncategorized")
        assert response.status_code == 200
        assert response.json() == []

    def test_groups_by_bank_category(self, client, db: Session):
        make_transaction(db, categorie="Boodschappen", bedrag=-10.0)
        make_transaction(db, categorie="Boodschappen", bedrag=-20.0)
        make_transaction(db, categorie="Horeca", bedrag=-15.0)
        db.commit()

        response = client.get("/api/uncategorized")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

        by_cat = {g["bank_category"]: g for g in data}
        assert by_cat["Boodschappen"]["count"] == 2
        assert by_cat["Boodschappen"]["total"] == 30.0
        assert by_cat["Horeca"]["count"] == 1
        assert by_cat["Horeca"]["total"] == 15.0

    def test_excludes_categorized_transactions(self, client, db: Session):
        cat = make_category(db, name="Food")
        make_transaction(db, categorie="Boodschappen", category_id=cat.id)
        make_transaction(db, categorie="Boodschappen")
        db.commit()

        response = client.get("/api/uncategorized")
        data = response.json()
        assert len(data) == 1
        assert data[0]["count"] == 1

    def test_excludes_income_transactions(self, client, db: Session):
        make_transaction(db, bedrag=100.0, categorie="Salaris")
        make_transaction(db, bedrag=-10.0, categorie="Boodschappen")
        db.commit()

        response = client.get("/api/uncategorized")
        data = response.json()
        assert len(data) == 1
        assert data[0]["bank_category"] == "Boodschappen"

    def test_sorted_by_total_descending(self, client, db: Session):
        make_transaction(db, categorie="Cheap", bedrag=-5.0)
        make_transaction(db, categorie="Expensive", bedrag=-100.0)
        db.commit()

        response = client.get("/api/uncategorized")
        data = response.json()
        assert data[0]["bank_category"] == "Expensive"
        assert data[1]["bank_category"] == "Cheap"
