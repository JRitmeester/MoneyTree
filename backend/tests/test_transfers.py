from datetime import date

from sqlalchemy.orm import Session

from app.models import OwnAccount
from app.services.transfers import (
    backfill_internal_transfers,
    normalize_iban,
    own_ibans,
    savings_balance,
)

from .conftest import make_transaction

SAVINGS_IBAN = "NL00ASNB0000000002"


def add_savings_account(db, *, starting_balance=None, starting_balance_date=None):
    acc = OwnAccount(
        iban=SAVINGS_IBAN,
        name="Spaarrekening",
        account_type="savings",
        starting_balance=starting_balance,
        starting_balance_date=starting_balance_date,
    )
    db.add(acc)
    db.flush()
    return acc


class TestNormalizeIban:
    def test_strips_spaces_and_uppercases(self):
        assert normalize_iban("nl26 asnb 8831 5278 78") == "NL26ASNB8831527878"


class TestBackfill:
    def test_flags_matching_counterparty(self, db: Session):
        add_savings_account(db)
        to_savings = make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN)
        unrelated = make_transaction(db, bedrag=-500.0, tegenrekening="NL99BANK0000000009")
        no_counterparty = make_transaction(db, bedrag=-25.0, tegenrekening=None)

        changed = backfill_internal_transfers(db)

        assert changed == 1
        assert to_savings.is_internal_transfer is True
        assert unrelated.is_internal_transfer is False
        assert no_counterparty.is_internal_transfer is False

    def test_unflags_when_account_removed(self, db: Session):
        tx = make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN)
        tx.is_internal_transfer = True
        db.flush()

        changed = backfill_internal_transfers(db)  # no own accounts exist

        assert changed == 1
        assert tx.is_internal_transfer is False

    def test_skips_manual_overrides(self, db: Session):
        add_savings_account(db)
        tx = make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN)
        tx.is_internal_transfer = False
        tx.is_internal_transfer_manual = True
        db.flush()

        changed = backfill_internal_transfers(db)

        assert changed == 0
        assert tx.is_internal_transfer is False

    def test_matches_despite_spacing_differences(self, db: Session):
        add_savings_account(db)
        tx = make_transaction(db, bedrag=-100.0, tegenrekening="nl00 asnb 0000 0000 02")
        backfill_internal_transfers(db)
        assert tx.is_internal_transfer is True


class TestSavingsBalance:
    def test_none_without_savings_account(self, db: Session):
        assert savings_balance(db) is None

    def test_net_only_without_starting_balance(self, db: Session):
        add_savings_account(db)
        make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN)
        make_transaction(db, bedrag=200.0, tegenrekening=SAVINGS_IBAN)
        backfill_internal_transfers(db)

        result = savings_balance(db)
        assert result.is_net_only is True
        assert result.balance == 300.0  # 500 in, 200 back out

    def test_starting_balance_and_date_cutoff(self, db: Session):
        add_savings_account(db, starting_balance=1000.0, starting_balance_date=date(2025, 1, 10))
        make_transaction(db, bedrag=-500.0, tegenrekening=SAVINGS_IBAN, datum=date(2025, 1, 15))
        make_transaction(db, bedrag=-999.0, tegenrekening=SAVINGS_IBAN, datum=date(2025, 1, 5))
        backfill_internal_transfers(db)

        result = savings_balance(db)
        assert result.is_net_only is False
        assert result.balance == 1500.0  # 1000 start + 500; the Jan 5 transfer predates the cutoff
        assert result.account_name == "Spaarrekening"
