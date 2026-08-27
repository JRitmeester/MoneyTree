from sqlalchemy.orm import Session

from .conftest import make_transaction


class TestAmountSearch:
    def test_dutch_comma_amount_matches_by_value(self, client, db: Session):
        make_transaction(db, bedrag=-46.95, omschrijving="Coffee shop", naam="Kaffee")
        db.commit()

        body = client.get("/api/transactions?search=46,95").json()
        assert body["total"] == 1
        assert body["items"][0]["bedrag"] == -46.95

    def test_dot_amount_also_matches(self, client, db: Session):
        make_transaction(db, bedrag=-46.95, omschrijving="Coffee shop", naam="Kaffee")
        db.commit()

        body = client.get("/api/transactions?search=46.95").json()
        assert body["total"] == 1
        assert body["items"][0]["bedrag"] == -46.95

    def test_text_search_still_works(self, client, db: Session):
        make_transaction(db, bedrag=-10.0, omschrijving="banana purchase", naam="Fruit shop")
        make_transaction(db, bedrag=-20.0, omschrijving="something else", naam="Other shop")
        db.commit()

        body = client.get("/api/transactions?search=banana").json()
        assert body["total"] == 1
        assert body["items"][0]["bedrag"] == -10.0

    def test_amount_search_tolerance(self, client, db: Session):
        make_transaction(db, bedrag=-46.951, omschrijving="Coffee shop", naam="Kaffee")
        db.commit()

        body = client.get("/api/transactions?search=46,95").json()
        assert body["total"] == 1

    def test_amount_search_with_minus_or_euro_sign(self, client, db: Session):
        make_transaction(db, bedrag=-46.95, omschrijving="Coffee shop", naam="Kaffee")
        db.commit()

        body_minus = client.get("/api/transactions?search=-46,95").json()
        assert body_minus["total"] == 1

        body_euro = client.get("/api/transactions?search=%E2%82%AC46,95").json()
        assert body_euro["total"] == 1

    def test_amount_search_ors_with_text_match(self, client, db: Session):
        make_transaction(db, bedrag=-46.95, omschrijving="no number here", naam="Kaffee")
        make_transaction(db, bedrag=-1.0, omschrijving="mentions 46,95 in text", naam="Other")
        db.commit()

        body = client.get("/api/transactions?search=46,95").json()
        assert body["total"] == 2
