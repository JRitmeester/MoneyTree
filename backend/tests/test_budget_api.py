"""Budget endpoint tests for derived-line behavior.

Spec: docs/superpowers/specs/2026-08-28-derived-budget-lines-design.md,
section "API and validation".
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import BudgetTemplate, Category, RecurringPayment


def _category(db: Session, name: str, *, is_fixed: bool = True) -> Category:
    cat = Category(name=name, category_type="expense", is_fixed=is_fixed)
    db.add(cat)
    db.commit()
    return cat


def _rent_payment(db: Session, category_id: int) -> RecurringPayment:
    payment = RecurringPayment(
        merchant_pattern="Rent", name="Rent", expected_amount=-1233,
        cadence="monthly", expected_day=3, anchor_date=date.today().replace(day=3),
        status="confirmed", is_income=False, category_id=category_id,
    )
    db.add(payment)
    db.commit()
    return payment


def _current_period() -> tuple[str, str]:
    today = date.today()
    start = today.replace(day=1)
    end = (start + timedelta(days=45)).replace(day=1)
    return start.isoformat(), end.isoformat()


class TestDerivedLinesInApi:
    def test_read_materializes_derived_line_with_source(self, client, db: Session):
        cat = _category(db, "Huur")
        _rent_payment(db, cat.id)
        start, end = _current_period()
        budget_id = client.post("/api/budgets", json={"start_date": start, "end_date": end}).json()["id"]

        body = client.get(f"/api/budgets/{budget_id}").json()
        line = next(l for l in body["lines"] if l["category_id"] == cat.id)
        assert line["amount"] == 1233.0
        assert line["source"] == "recurring"

    def test_update_preserves_derived_row_id_and_ignores_ridealong(self, client, db: Session):
        cat = _category(db, "Huur")
        manual_cat = _category(db, "Boodschappen", is_fixed=False)
        _rent_payment(db, cat.id)
        start, end = _current_period()
        budget_id = client.post("/api/budgets", json={"start_date": start, "end_date": end}).json()["id"]

        body = client.get(f"/api/budgets/{budget_id}").json()
        derived_id = next(l["id"] for l in body["lines"] if l["category_id"] == cat.id)

        # Auto-save sends everything back, including the derived line with a
        # user-impossible amount and a new manual line.
        resp = client.put(f"/api/budgets/{budget_id}", json={"lines": [
            {"category_id": cat.id, "amount": 1.0},
            {"category_id": manual_cat.id, "amount": 350.0},
        ]})
        assert resp.status_code == 200
        lines = {l["category_id"]: l for l in resp.json()["lines"]}
        assert lines[cat.id]["amount"] == 1233.0
        assert lines[cat.id]["source"] == "recurring"
        assert lines[cat.id]["id"] == derived_id
        assert lines[manual_cat.id]["amount"] == 350.0
        assert lines[manual_cat.id]["source"] == "manual"

    def test_manual_lines_still_replaceable(self, client, db: Session):
        manual_cat = _category(db, "Boodschappen", is_fixed=False)
        start, end = _current_period()
        budget_id = client.post("/api/budgets", json={
            "start_date": start, "end_date": end,
            "lines": [{"category_id": manual_cat.id, "amount": 300.0}],
        }).json()["id"]

        resp = client.put(f"/api/budgets/{budget_id}", json={"lines": []})
        assert resp.status_code == 200
        assert resp.json()["lines"] == []

    def test_template_creation_skips_deriving_categories(self, client, db: Session):
        cat = _category(db, "Huur")
        _rent_payment(db, cat.id)
        db.add(BudgetTemplate(category_id=cat.id, amount=999.0))
        db.commit()
        start, end = _current_period()

        body = client.post("/api/budgets", json={"start_date": start, "end_date": end}).json()
        line = next(l for l in body["lines"] if l["category_id"] == cat.id)
        # The derived line wins; the stale template amount never lands.
        assert line["amount"] == 1233.0
        assert line["source"] == "recurring"
