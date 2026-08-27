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


class TestTransactionFlagsApi:
    def test_patch_is_incidental(self, client, db: Session):
        tx = make_transaction(db, bedrag=-1340.0)
        db.commit()
        resp = client.patch(f"/api/transactions/{tx.id}", json={"is_incidental": True})
        assert resp.status_code == 200
        assert resp.json()["is_incidental"] is True

    def test_patch_transfer_flag_sets_manual(self, client, db: Session):
        tx = make_transaction(db, bedrag=-500.0)
        db.commit()
        resp = client.patch(f"/api/transactions/{tx.id}", json={"is_internal_transfer": True})
        assert resp.status_code == 200
        assert resp.json()["is_internal_transfer"] is True
        db.refresh(tx)
        assert tx.is_internal_transfer_manual is True

    def test_manual_flag_survives_backfill(self, client, db: Session):
        tx = make_transaction(db, bedrag=-500.0, tegenrekening="NL99BANK0000000009")
        db.commit()
        client.patch(f"/api/transactions/{tx.id}", json={"is_internal_transfer": True})
        changed = backfill_internal_transfers(db)
        db.refresh(tx)
        assert tx.is_internal_transfer is True
        assert changed == 0

    def test_bulk_incidental(self, client, db: Session):
        a = make_transaction(db, bedrag=-100.0)
        b = make_transaction(db, bedrag=-200.0)
        db.commit()
        resp = client.post("/api/transactions/bulk-incidental", json={
            "transaction_ids": [a.id, b.id, 99999],
            "is_incidental": True,
        })
        assert resp.status_code == 200
        assert resp.json()["updated"] == 2
        db.refresh(a)
        assert a.is_incidental is True

    def test_list_includes_flags(self, client, db: Session):
        make_transaction(db, bedrag=-100.0)
        db.commit()
        item = client.get("/api/transactions").json()["items"][0]
        assert item["is_internal_transfer"] is False
        assert item["is_incidental"] is False


class TestImportFlagsTransfers:
    def test_import_flags_transfer_rows(self, client, db: Session):
        db.add(OwnAccount(iban="NL00ASNB0000000002", name="Spaar", account_type="savings"))
        db.commit()
        csv_content = (
            'Datum;Rekening;Tegenrekening;Naam;Adres;Postcode;Plaats;Valutasoort saldo;'
            'Saldo voor boeking;Valutasoort mutatie;Bedrag;Verwerkingsdatum;Valutadatum;'
            'Code;Batchnummer;Volgnummer;Betalingskenmerk;Omschrijving;Afschriftnummer;'
            'Transactietype\n'
            '01-08-2026;NL00TEST0000000001;NL00ASNB0000000002;J TEST;;;;EUR;1000,00;EUR;'
            '-500,00;01-08-2026;01-08-2026;GT;OVB;001;;Huur naar spaarpot;0001;Overboeking\n'
            '02-08-2026;NL00TEST0000000001;NL99BANK0000000009;SHOP;;;;EUR;500,00;EUR;'
            '-25,00;02-08-2026;02-08-2026;GT;BEA;002;;Boodschappen;0001;Boodschappen\n'
        )
        resp = client.post(
            "/api/transactions/import",
            files={"file": ("test.csv", csv_content.encode(), "text/csv")},
        )
        assert resp.status_code == 200
        assert resp.json()["imported"] == 2
        from app.models import Transaction
        from sqlalchemy import select
        txs = db.execute(select(Transaction).order_by(Transaction.datum)).scalars().all()
        assert txs[0].is_internal_transfer is True
        assert txs[1].is_internal_transfer is False
