from datetime import date

from sqlalchemy.orm import Session

from app.models import OwnAccount
from app.services.transfers import backfill_internal_transfers

from .conftest import make_transaction

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
        make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN, categorie="Overboeking")
        backfill_internal_transfers(db)
        db.commit()
        assert client.get("/api/dashboard/by-category").json() == []


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
