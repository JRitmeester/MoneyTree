from sqlalchemy.orm import Session

from app.models import CategoryMapping
from tests.conftest import make_category


CSV_HEADER = (
    'Datum;Rekening;Tegenrekening;Naam;Adres;Postcode;Plaats;Valutasoort saldo;'
    'Saldo voor boeking;Valutasoort mutatie;Bedrag;Verwerkingsdatum;Valutadatum;'
    'Code;Batchnummer;Volgnummer;Betalingskenmerk;Omschrijving;Afschriftnummer;'
    'Transactietype\n'
)


def make_row(
    *,
    datum="01-08-2026",
    bedrag="-25,00",
    volgnummer="001",
    categorie="Boodschappen",
    omschrijving="Boodschappen",
):
    return (
        f'{datum};NL00TEST0000000001;NL99BANK0000000009;SHOP;;;;EUR;500,00;EUR;'
        f'{bedrag};{datum};{datum};GT;BEA;{volgnummer};;{omschrijving};0001;{categorie}\n'
    )


class TestImportErrors:
    def test_bad_amount_returns_400_with_row_number(self, client):
        csv_content = (
            CSV_HEADER
            + make_row(volgnummer="001")
            + make_row(volgnummer="002")
            + make_row(volgnummer="003", bedrag="not-a-number")
        )
        resp = client.post(
            "/api/transactions/import",
            files={"file": ("test.csv", csv_content.encode(), "text/csv")},
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "row 3" in detail.lower()

    def test_garbage_bytes_return_400_not_500(self, client):
        resp = client.post(
            "/api/transactions/import",
            files={"file": ("test.csv", b"\x00\x01\x02garbage not a csv at all", "text/csv")},
        )
        assert resp.status_code == 400
        assert resp.status_code != 500

    def test_bad_date_returns_400_with_row_number(self, client):
        csv_content = (
            CSV_HEADER
            + make_row(volgnummer="001")
            + make_row(volgnummer="002", datum="not-a-date")
        )
        resp = client.post(
            "/api/transactions/import",
            files={"file": ("test.csv", csv_content.encode(), "text/csv")},
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "row 2" in detail.lower()


class TestImportCategorizationCounts:
    def test_counts_categorized_and_uncategorized_rows(self, client, db: Session):
        category = make_category(db, name="Groceries")
        db.add(CategoryMapping(bank_category="Boodschappen", category_id=category.id))
        db.commit()

        csv_content = (
            CSV_HEADER
            + make_row(volgnummer="001", categorie="Boodschappen")
            + make_row(volgnummer="002", categorie="Overig")
        )
        resp = client.post(
            "/api/transactions/import",
            files={"file": ("test.csv", csv_content.encode(), "text/csv")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["imported"] == 2
        assert body["categorized"] == 1
        assert body["uncategorized"] == 1
