from datetime import date

from sqlalchemy.orm import Session

from .conftest import make_category, make_transaction


class TestIcsSummaryCard:
    def test_ics_total_sums_matching_expenses(self, client, db: Session):
        make_transaction(db, bedrag=-100.0, naam="International Card Services BV")
        make_transaction(db, bedrag=-50.0, naam="Some Other Shop")
        db.commit()

        body = client.get("/api/dashboard/summary").json()
        assert body["ics_total"] == 100.0

    def test_ics_total_matches_on_merchant_name_field(self, client, db: Session):
        make_transaction(db, bedrag=-25.0, naam=None, merchant_name="ICS")
        db.commit()

        body = client.get("/api/dashboard/summary").json()
        assert body["ics_total"] == 25.0

    def test_ics_total_does_not_match_lookalike(self, client, db: Session):
        make_transaction(db, bedrag=-25.0, naam="PICSNIC Restaurant")
        db.commit()

        body = client.get("/api/dashboard/summary").json()
        assert body["ics_total"] == 0.0

    def test_ics_total_defaults_to_zero(self, client, db: Session):
        body = client.get("/api/dashboard/summary").json()
        assert body["ics_total"] == 0.0

    def test_ics_total_respects_date_filter(self, client, db: Session):
        make_transaction(db, bedrag=-100.0, naam="International Card Services", datum=date(2024, 1, 1))
        make_transaction(db, bedrag=-40.0, naam="International Card Services", datum=date(2025, 6, 1))
        db.commit()

        body = client.get("/api/dashboard/summary?date_from=2025-01-01&date_to=2025-12-31").json()
        assert body["ics_total"] == 40.0


class TestYearReview:
    def test_default_year_is_current_year(self, client):
        body = client.get("/api/dashboard/year-review").json()
        assert body["year"] == date.today().year

    def test_income_expense_net_for_year(self, client, db: Session):
        make_transaction(db, bedrag=3000.0, datum=date(2025, 3, 1))
        make_transaction(db, bedrag=-100.0, datum=date(2025, 3, 5))
        make_transaction(db, bedrag=-1000.0, datum=date(2024, 3, 5))  # different year
        db.commit()

        body = client.get("/api/dashboard/year-review?year=2025").json()
        assert body["income"] == 3000.0
        assert body["expenses"] == 100.0
        assert body["net"] == 2900.0
        assert body["previous_year"]["year"] == 2024
        assert body["previous_year"]["expenses"] == 1000.0

    def test_root_category_rollup_with_delta(self, client, db: Session):
        parent = make_category(db, name="Vervoer")
        child = make_category(db, name="Auto")
        child.parent_id = parent.id
        db.flush()

        make_transaction(db, bedrag=-200.0, category_id=child.id, datum=date(2025, 4, 1))
        make_transaction(db, bedrag=-50.0, category_id=child.id, datum=date(2024, 4, 1))
        db.commit()

        body = client.get("/api/dashboard/year-review?year=2025").json()
        row = next(r for r in body["by_root_category"] if r["category_id"] == parent.id)
        assert row["name"] == "Vervoer"
        assert row["total"] == 200.0
        assert row["previous_total"] == 50.0
        assert row["delta"] == 150.0

    def test_uncategorized_row_included(self, client, db: Session):
        make_transaction(db, bedrag=-75.0, category_id=None, datum=date(2025, 5, 1))
        db.commit()

        body = client.get("/api/dashboard/year-review?year=2025").json()
        row = next(r for r in body["by_root_category"] if r["category_id"] is None)
        assert row["name"] == "Uncategorized"
        assert row["total"] == 75.0
