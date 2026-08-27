from datetime import date

from sqlalchemy.orm import Session

from app.models import OwnAccount
from app.services.transfers import backfill_internal_transfers

from .conftest import make_category, make_transaction

SAVINGS_IBAN = "NL00ASNB0000000002"


def setup_savings(db, **kwargs):
    db.add(OwnAccount(iban=SAVINGS_IBAN, name="Spaar", account_type="savings", **kwargs))
    db.flush()


class TestSummaryExcludesTransfers:
    def test_transfers_not_income_or_expense(self, client, db: Session):
        setup_savings(db)
        make_transaction(db, bedrag=3000.0)                                  # salary
        make_transaction(db, bedrag=-100.0)                                  # real expense
        make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN)      # to savings
        make_transaction(db, bedrag=200.0, tegenrekening=SAVINGS_IBAN)       # back from savings
        backfill_internal_transfers(db)
        db.commit()

        body = client.get("/api/dashboard/summary").json()
        assert body["total_income"] == 3000.0
        assert body["total_expenses"] == 100.0
        assert body["net"] == 2900.0
        assert body["transaction_count"] == 2
        assert body["transfers_out"] == 500.0
        assert body["transfers_in"] == 200.0
        assert body["transfers_net"] == 300.0


class TestByCategoryExcludesTransfers:
    def test_transfer_not_in_category_spending(self, client, db: Session):
        setup_savings(db)
        cat = make_category(db, name="Sparen")
        make_transaction(
            db,
            bedrag=-500.0,
            tegenrekening=SAVINGS_IBAN,
            categorie="Overboeking",
            category_id=cat.id,
        )
        backfill_internal_transfers(db)
        db.commit()

        # Transfer is flagged and categorized: it must not appear.
        assert client.get("/api/dashboard/by-category").json() == []

        # A real, non-transfer categorized expense in the same category
        # DOES appear, proving the filter discriminates on the flag
        # rather than accidentally hiding the whole category.
        make_transaction(db, bedrag=-50.0, categorie="Boodschappen", category_id=cat.id)
        db.commit()

        result = client.get("/api/dashboard/by-category").json()
        assert len(result) == 1
        assert result[0]["category_id"] == cat.id
        assert result[0]["total"] == 50.0


class TestMonthlyTrendExcludesTransfers:
    def test_trend_skips_transfers(self, client, db: Session):
        setup_savings(db)
        make_transaction(db, bedrag=-100.0, datum=date(2025, 1, 10))
        make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN, datum=date(2025, 1, 12))
        backfill_internal_transfers(db)
        db.commit()

        months = client.get("/api/dashboard/monthly-trend").json()
        jan = next(m for m in months if m["month"] == "2025-01")
        assert jan["expenses"] == 100.0


class TestSavingsBalanceEndpoint:
    def test_null_without_savings_account(self, client):
        resp = client.get("/api/dashboard/savings-balance")
        assert resp.status_code == 200
        assert resp.json() is None

    def test_balance_with_starting_balance(self, client, db: Session):
        setup_savings(db, starting_balance=1000.0, starting_balance_date=date(2025, 1, 1))
        make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN, datum=date(2025, 1, 15))
        backfill_internal_transfers(db)
        db.commit()

        body = client.get("/api/dashboard/savings-balance").json()
        assert body["balance"] == 1500.0
        assert body["is_net_only"] is False
        assert body["account_name"] == "Spaar"


class TestBalanceHistory:
    def test_daily_end_of_day_balance(self, client, db: Session):
        # Two transactions on the same day: the later volgnummer wins.
        make_transaction(db, datum=date(2025, 1, 10), saldo_voor_boeking=1000.0,
                         bedrag=-100.0, volgnummer="001")
        make_transaction(db, datum=date(2025, 1, 10), saldo_voor_boeking=900.0,
                         bedrag=-50.0, volgnummer="002")
        make_transaction(db, datum=date(2025, 1, 12), saldo_voor_boeking=850.0,
                         bedrag=200.0, volgnummer="003")
        db.commit()

        points = client.get("/api/dashboard/balance-history").json()
        assert points == [
            {"date": "2025-01-10", "balance": 850.0},
            {"date": "2025-01-12", "balance": 1050.0},
        ]

    def test_date_range_filter(self, client, db: Session):
        make_transaction(db, datum=date(2025, 1, 10), saldo_voor_boeking=1000.0, bedrag=-100.0)
        make_transaction(db, datum=date(2025, 2, 10), saldo_voor_boeking=900.0, bedrag=-100.0)
        db.commit()

        points = client.get(
            "/api/dashboard/balance-history?date_from=2025-02-01"
        ).json()
        assert len(points) == 1
        assert points[0]["date"] == "2025-02-10"


class TestSavingsCapacity:
    def _seed_month(self, db, year, month, *, income=3000.0, spend=2000.0, incidental=0.0):
        from calendar import monthrange
        make_transaction(db, bedrag=income, datum=date(year, month, 1))
        make_transaction(db, bedrag=-spend, datum=date(year, month, 5))
        if incidental:
            make_transaction(db, bedrag=-incidental, datum=date(year, month, 6), is_incidental=True)
        # Anchor the month edges so completeness detection sees full coverage.
        make_transaction(db, bedrag=-1.0, datum=date(year, month, monthrange(year, month)[1]))

    def test_monthly_series_and_structural_net(self, client, db: Session):
        self._seed_month(db, 2025, 1, income=3000.0, spend=2000.0, incidental=500.0)
        db.commit()

        body = client.get("/api/dashboard/savings-capacity").json()
        jan = next(m for m in body["months"] if m["month"] == "2025-01")
        assert jan["income"] == 3000.0
        assert jan["expenses_total"] == 2501.0
        assert jan["incidental"] == 500.0
        assert jan["expenses_structural"] == 2001.0
        assert jan["net_raw"] == 499.0
        assert jan["net_structural"] == 999.0
        assert jan["partial"] is False

    def test_excludes_internal_transfers(self, client, db: Session):
        setup_savings(db)
        self._seed_month(db, 2025, 1)
        make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN, datum=date(2025, 1, 20))
        backfill_internal_transfers(db)
        db.commit()

        jan = next(m for m in client.get("/api/dashboard/savings-capacity").json()["months"]
                   if m["month"] == "2025-01")
        assert jan["expenses_total"] == 2001.0

    def test_partial_month_flagged_and_excluded_from_averages(self, client, db: Session):
        for m in (1, 2, 3):
            self._seed_month(db, 2025, m)
        # April only has data up to the 10th: partial.
        make_transaction(db, bedrag=-100.0, datum=date(2025, 4, 10))
        db.commit()

        body = client.get("/api/dashboard/savings-capacity").json()
        apr = next(m for m in body["months"] if m["month"] == "2025-04")
        assert apr["partial"] is True
        # Averages over the 3 complete months: each has net_raw 999.0.
        assert body["trailing_3_raw"] == 999.0
        assert body["trailing_6_raw"] is None  # only 3 complete months exist

    def test_fixed_flexible_uncategorized_split(self, client, db: Session):
        from .conftest import make_category
        from app.models import Category
        fixed_cat = Category(name="Huur", is_fixed=True, category_type="expense")
        flex_cat = Category(name="Boodschappen", is_fixed=False, category_type="expense")
        db.add_all([fixed_cat, flex_cat])
        db.flush()
        make_transaction(db, bedrag=-1200.0, datum=date(2025, 1, 2), category_id=fixed_cat.id)
        make_transaction(db, bedrag=-300.0, datum=date(2025, 1, 3), category_id=flex_cat.id)
        make_transaction(db, bedrag=-50.0, datum=date(2025, 1, 4), category_id=None)
        db.commit()

        jan = next(m for m in client.get("/api/dashboard/savings-capacity").json()["months"]
                   if m["month"] == "2025-01")
        assert jan["fixed"] == 1200.0
        assert jan["flexible"] == 300.0
        assert jan["uncategorized"] == 50.0

    def test_trailing_6_not_starved_by_partial_current_month(self, client, db: Session):
        # 7 fully complete months, then a partial current (8th) month.
        for m in range(1, 8):
            self._seed_month(db, 2025, m)
        make_transaction(db, bedrag=-100.0, datum=date(2025, 8, 10))
        db.commit()

        body = client.get("/api/dashboard/savings-capacity").json()
        # Display window (default months=6) still returns exactly 6 entries.
        assert len(body["months"]) == 6
        # Averaging pool is drawn from the full history's complete months
        # (months 1-7), not just the 6-month display window (months 3-8,
        # which would only contain 5 complete months and starve trailing_6).
        assert body["trailing_6_raw"] is not None
        assert body["trailing_6_raw"] == 999.0

    def test_empty_database(self, client):
        body = client.get("/api/dashboard/savings-capacity").json()
        assert body["months"] == []
        assert body["trailing_3_structural"] is None
        assert body["current_month_projection"] is None


class TestCategoryLineItemGroups:
    def _tree(self, db):
        from app.models import Category
        parent = Category(name="Vrije Tijd", category_type="expense")
        db.add(parent)
        db.flush()
        child_a = Category(name="Hobby", parent_id=parent.id, category_type="expense")
        child_b = Category(name="Uitgaan", parent_id=parent.id, category_type="expense")
        db.add_all([child_a, child_b])
        db.flush()
        grandchild = Category(name="Lego", parent_id=child_a.id, category_type="expense")
        db.add(grandchild)
        db.flush()
        return parent, child_a, child_b, grandchild

    def test_direct_items_and_child_groups(self, client, db: Session):
        parent, child_a, child_b, grandchild = self._tree(db)
        make_transaction(db, bedrag=-10.0, category_id=parent.id, datum=date(2026, 8, 1))
        make_transaction(db, bedrag=-20.0, category_id=child_a.id, datum=date(2026, 8, 2))
        make_transaction(db, bedrag=-40.0, category_id=grandchild.id, datum=date(2026, 8, 3))
        make_transaction(db, bedrag=-5.0, category_id=child_b.id, datum=date(2026, 8, 4))
        db.commit()

        body = client.get(f"/api/dashboard/category/{parent.id}/line-items").json()

        assert body["total"] == 75.0
        # Direct items: only the transaction categorized on the parent itself.
        assert [li["amount"] for li in body["line_items"]] == [10.0]

        # One group per direct child with spending, sorted by total descending.
        groups = body["groups"]
        assert [g["category_name"] for g in groups] == ["Hobby", "Uitgaan"]
        hobby = groups[0]
        assert hobby["category_id"] == child_a.id
        assert hobby["total"] == 60.0
        # Grandchild items roll up into the direct child's group, newest first.
        assert [li["amount"] for li in hobby["line_items"]] == [40.0, 20.0]
        assert groups[1]["total"] == 5.0

    def test_leaf_category_has_no_groups(self, client, db: Session):
        parent, child_a, child_b, grandchild = self._tree(db)
        make_transaction(db, bedrag=-40.0, category_id=grandchild.id, datum=date(2026, 8, 3))
        db.commit()

        body = client.get(f"/api/dashboard/category/{grandchild.id}/line-items").json()
        assert body["groups"] == []
        assert [li["amount"] for li in body["line_items"]] == [40.0]
