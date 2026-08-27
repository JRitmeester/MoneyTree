from datetime import date

from sqlalchemy.orm import Session

from .conftest import make_transaction


def link_offset(client, expense_id: int, income_id: int):
    resp = client.post(f"/api/transactions/{expense_id}/offsets/{income_id}")
    assert resp.status_code == 200, resp.text
    return resp


class TestTransactionListOffsetFields:
    def test_defaults_to_zero_and_false(self, client, db: Session):
        make_transaction(db, bedrag=-10.0, datum=date(2025, 3, 1))
        db.commit()

        item = client.get("/api/transactions").json()["items"][0]
        assert item["offset_total"] == 0.0
        assert item["is_offset_income"] is False

    def test_expense_shows_offset_total(self, client, db: Session):
        expense = make_transaction(db, bedrag=-100.0, datum=date(2025, 3, 1))
        income = make_transaction(db, bedrag=30.0, datum=date(2025, 3, 2))
        db.commit()
        link_offset(client, expense.id, income.id)

        items = {i["id"]: i for i in client.get("/api/transactions").json()["items"]}
        assert items[expense.id]["offset_total"] == 30.0
        assert items[expense.id]["is_offset_income"] is False
        assert items[income.id]["is_offset_income"] is True
        assert items[income.id]["offset_total"] == 0.0

    def test_multiple_offsets_summed(self, client, db: Session):
        expense = make_transaction(db, bedrag=-100.0, datum=date(2025, 3, 1))
        income1 = make_transaction(db, bedrag=20.0, datum=date(2025, 3, 2))
        income2 = make_transaction(db, bedrag=15.0, datum=date(2025, 3, 3))
        db.commit()
        link_offset(client, expense.id, income1.id)
        link_offset(client, expense.id, income2.id)

        items = {i["id"]: i for i in client.get("/api/transactions").json()["items"]}
        assert items[expense.id]["offset_total"] == 35.0
