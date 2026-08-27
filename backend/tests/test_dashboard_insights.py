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
