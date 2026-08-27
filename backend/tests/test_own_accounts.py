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
