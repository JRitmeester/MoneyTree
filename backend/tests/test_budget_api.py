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


class TestBudgetVsActualBoundary:
    def test_end_date_transaction_belongs_to_next_period(self, client, db: Session):
        """Budget periods are half-open [start_date, end_date): a salary
        landing exactly on end_date is the NEXT period's income. Regression:
        the actuals query used an inclusive end, double-counting boundary-day
        transactions in consecutive periods."""
        from .conftest import make_transaction

        salaris = Category(name="Salaris", category_type="income")
        db.add(salaris)
        db.commit()

        client.post("/api/budgets", json={"start_date": "2026-08-21", "end_date": "2026-09-23"})
        client.post("/api/budgets", json={"start_date": "2026-09-23", "end_date": "2026-10-22"})
        first_id, second_id = [b["id"] for b in reversed(client.get("/api/budgets").json())]

        make_transaction(db, bedrag=3227.34, datum=date(2026, 8, 21), category_id=salaris.id)
        make_transaction(db, bedrag=3583.48, datum=date(2026, 9, 23), category_id=salaris.id)
        db.commit()

        first = client.get(f"/api/dashboard/budget-vs-actual/{first_id}").json()
        second = client.get(f"/api/dashboard/budget-vs-actual/{second_id}").json()
        assert first["total_actual_income"] == 3227.34
        assert second["total_actual_income"] == 3583.48


class TestBudgetVsActualSource:
    def test_bva_lines_carry_budget_line_source(self, client, db: Session):
        """The Actuals view sections lines the same way the Plan tab does:
        by the budget line's source. The BVA payload must therefore carry
        it (default 'manual' for actuals-only categories)."""
        from .conftest import make_transaction

        cat = _category(db, "Huur")
        loose = _category(db, "Snacks", is_fixed=False)
        _rent_payment(db, cat.id)
        start, end = _current_period()
        budget_id = client.post("/api/budgets", json={"start_date": start, "end_date": end}).json()["id"]
        make_transaction(db, bedrag=-9.5, datum=date.today(), category_id=loose.id)
        db.commit()

        body = client.get(f"/api/dashboard/budget-vs-actual/{budget_id}").json()
        by_cat = {l["category_id"]: l for l in body["expense_lines"]}
        assert by_cat[cat.id]["source"] == "recurring"
        assert by_cat[loose.id]["source"] == "manual"


class TestSavingsContributions:
    def test_savings_actual_is_net_contributed_transfers(self, client, db: Session):
        """For savings-type categories, 'actual' answers 'did I put money
        toward this goal this period': the net of internal transfers
        categorized to the pot (deposits positive, withdrawals negative),
        instead of always-zero spending."""
        from .conftest import make_transaction

        pot = Category(name="Autofonds", category_type="savings", is_fixed=True)
        db.add(pot)
        db.commit()
        start, end = _current_period()
        budget_id = client.post("/api/budgets", json={
            "start_date": start, "end_date": end,
            "lines": [{"category_id": pot.id, "amount": 100.0}],
        }).json()["id"]

        deposit = make_transaction(db, bedrag=-150.0, datum=date.today(), category_id=pot.id)
        deposit.is_internal_transfer = True
        withdrawal = make_transaction(db, bedrag=50.0, datum=date.today(), category_id=pot.id)
        withdrawal.is_internal_transfer = True
        db.commit()

        body = client.get(f"/api/dashboard/budget-vs-actual/{budget_id}").json()
        line = next(l for l in body["expense_lines"] if l["category_id"] == pot.id)
        assert line["actual"] == 100.0  # 150 in, 50 back out


class TestHighlightsEndpoint:
    def test_highlights_response_shape(self, client, db: Session):
        """Test highlights endpoint returns correct response shape."""
        from .conftest import make_transaction

        fixed_cat = _category(db, "Huur")
        flexible_cat = _category(db, "Boodschappen", is_fixed=False)
        _rent_payment(db, fixed_cat.id)
        start, end = _current_period()

        budget_id = client.post("/api/budgets", json={
            "start_date": start, "end_date": end,
            "lines": [
                {"category_id": fixed_cat.id, "amount": 1233.0},
                {"category_id": flexible_cat.id, "amount": 300.0},
            ],
        }).json()["id"]

        make_transaction(db, bedrag=-50.0, datum=date.today(), category_id=flexible_cat.id)
        db.commit()

        resp = client.get(f"/api/budgets/{budget_id}/highlights")
        assert resp.status_code == 200

        body = resp.json()
        assert "budget_id" in body
        assert body["budget_id"] == budget_id
        assert "start_date" in body
        assert "end_date" in body
        assert "closed" in body
        assert isinstance(body["closed"], bool)
        assert "summary" in body

        summary = body["summary"]
        assert "raw_net" in summary
        assert "incidental_total" in summary
        assert "incidental_by_label" in summary
        assert isinstance(summary["incidental_by_label"], list)
        assert "unlabeled_incidental" in summary
        assert "structural_net" in summary
        assert "flexible_within_plan" in summary
        assert "flexible_total" in summary
        assert "pots_executed" in summary
        assert "pots_planned" in summary

        assert "highlights" in body
        assert isinstance(body["highlights"], list)
        for h in body["highlights"]:
            assert "rule" in h
            assert "severity" in h
            assert "title" in h
            assert "detail" in h
            assert "category_id" in h
            assert "amount" in h

    def test_highlights_404_on_unknown_budget(self, client):
        """Test highlights endpoint returns 404 for unknown budget."""
        resp = client.get("/api/budgets/99999/highlights")
        assert resp.status_code == 404

    def test_highlights_closed_flag_for_past_budget(self, client, db: Session):
        """Test closed flag is true for a past budget period."""
        fixed_cat = _category(db, "Huur")
        _rent_payment(db, fixed_cat.id)

        past_start = (date.today() - timedelta(days=60)).isoformat()
        past_end = (date.today() - timedelta(days=30)).isoformat()

        budget_id = client.post("/api/budgets", json={
            "start_date": past_start, "end_date": past_end,
            "lines": [{"category_id": fixed_cat.id, "amount": 1233.0}],
        }).json()["id"]

        resp = client.get(f"/api/budgets/{budget_id}/highlights")
        assert resp.status_code == 200
        assert resp.json()["closed"] is True

    def test_highlights_closed_flag_for_current_budget(self, client, db: Session):
        """Test closed flag is false for a current/open budget period."""
        fixed_cat = _category(db, "Huur")
        _rent_payment(db, fixed_cat.id)
        start, end = _current_period()

        budget_id = client.post("/api/budgets", json={
            "start_date": start, "end_date": end,
            "lines": [{"category_id": fixed_cat.id, "amount": 1233.0}],
        }).json()["id"]

        resp = client.get(f"/api/budgets/{budget_id}/highlights")
        assert resp.status_code == 200
        assert resp.json()["closed"] is False
