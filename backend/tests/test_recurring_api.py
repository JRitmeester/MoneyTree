"""Tests for the recurring-payment lifecycle API: list/confirm/dismiss/patch,
rescan, occurrences, import-time matching, and notices.

See docs/superpowers/specs/2026-08-27-financial-insights-design.md,
"Recurring-payment detection" Lifecycle paragraph.
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import RecurringPayment, RecurringPaymentOccurrence, Transaction
from app.services.recurring_detector import (
    detect_recurring_payments,
    next_expected_date,
    upsert_recurring_payments,
)

from .conftest import make_transaction


def _monthly_dates(start: date, count: int) -> list[date]:
    dates = []
    for i in range(count):
        dates.append(date(start.year, start.month, start.day) + timedelta(days=30 * i))
    return dates


def _seed_monthly_group(db: Session, count: int = 4, amount: float = -12.99, start: date = date(2025, 1, 15)):
    dates = _monthly_dates(start, count)
    for i, d in enumerate(dates):
        make_transaction(
            db, bedrag=amount, naam="Netflix", merchant_name="Netflix", datum=d, volgnummer=str(i + 1)
        )
    db.commit()


def _run_detector(db: Session) -> list[RecurringPayment]:
    candidates = detect_recurring_payments(db)
    rows = upsert_recurring_payments(db, candidates)
    db.commit()
    return rows


class TestListAndRescan:
    def test_rescan_creates_suggested_row(self, client, db: Session):
        _seed_monthly_group(db)
        resp = client.post("/api/recurring/rescan")
        assert resp.status_code == 200
        body = resp.json()
        assert body["suggested"] == 1
        assert body["confirmed"] == 0

    def test_list_filters_by_status(self, client, db: Session):
        _seed_monthly_group(db)
        client.post("/api/recurring/rescan")

        resp = client.get("/api/recurring", params={"status": "suggested"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        resp = client.get("/api/recurring", params={"status": "confirmed"})
        assert resp.json() == []

    def test_list_no_filter_returns_all(self, client, db: Session):
        _seed_monthly_group(db)
        client.post("/api/recurring/rescan")
        resp = client.get("/api/recurring")
        assert len(resp.json()) == 1


class TestConfirmAndDismiss:
    def test_confirm_sets_status_and_backfills_occurrences(self, client, db: Session):
        _seed_monthly_group(db, count=4)
        client.post("/api/recurring/rescan")
        payment_id = client.get("/api/recurring").json()[0]["id"]

        resp = client.post(f"/api/recurring/{payment_id}/confirm", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "confirmed"
        assert body["next_expected"] is not None

        occ_resp = client.get(f"/api/recurring/{payment_id}/occurrences")
        assert occ_resp.status_code == 200
        assert len(occ_resp.json()) == 4

    def test_confirm_accepts_name_and_category_override(self, client, db: Session):
        _seed_monthly_group(db)
        client.post("/api/recurring/rescan")
        payment_id = client.get("/api/recurring").json()[0]["id"]

        resp = client.post(
            f"/api/recurring/{payment_id}/confirm", json={"name": "Streaming"}
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Streaming"

    def test_confirm_missing_returns_404(self, client):
        resp = client.post("/api/recurring/999/confirm", json={})
        assert resp.status_code == 404

    def test_confirm_dismissed_rejected(self, client, db: Session):
        _seed_monthly_group(db)
        client.post("/api/recurring/rescan")
        payment_id = client.get("/api/recurring").json()[0]["id"]
        client.post(f"/api/recurring/{payment_id}/dismiss")

        resp = client.post(f"/api/recurring/{payment_id}/confirm", json={})
        assert resp.status_code == 409

    def test_dismiss_sets_status(self, client, db: Session):
        _seed_monthly_group(db)
        client.post("/api/recurring/rescan")
        payment_id = client.get("/api/recurring").json()[0]["id"]

        resp = client.post(f"/api/recurring/{payment_id}/dismiss")
        assert resp.status_code == 200
        assert resp.json()["status"] == "dismissed"

    def test_rescan_never_touches_confirmed_or_dismissed(self, client, db: Session):
        _seed_monthly_group(db)
        client.post("/api/recurring/rescan")
        payment_id = client.get("/api/recurring").json()[0]["id"]
        client.post(f"/api/recurring/{payment_id}/confirm", json={"name": "Kept Name"})

        client.post("/api/recurring/rescan")
        resp = client.get(f"/api/recurring")
        confirmed = [p for p in resp.json() if p["status"] == "confirmed"]
        assert len(confirmed) == 1
        assert confirmed[0]["name"] == "Kept Name"


class TestPatch:
    def test_patch_updates_fields(self, client, db: Session):
        _seed_monthly_group(db)
        client.post("/api/recurring/rescan")
        payment_id = client.get("/api/recurring").json()[0]["id"]

        resp = client.patch(
            f"/api/recurring/{payment_id}",
            json={"expected_amount": -15.0, "amount_tolerance": 0.2, "status": "confirmed"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["expected_amount"] == -15.0
        assert body["amount_tolerance"] == 0.2
        assert body["status"] == "confirmed"

    def test_patch_missing_returns_404(self, client):
        resp = client.patch("/api/recurring/999", json={"name": "X"})
        assert resp.status_code == 404


class TestNextExpected:
    def test_monthly_next_expected_one_month_after_anchor(self, db: Session):
        payment = RecurringPayment(
            merchant_pattern="netflix",
            name="Netflix",
            expected_amount=-12.99,
            cadence="monthly",
            expected_day=15,
            anchor_date=date(2025, 4, 15),
            status="confirmed",
        )
        db.add(payment)
        db.flush()
        assert next_expected_date(payment) == date(2025, 5, 15)

    def test_four_weekly_next_expected_28_days_after_anchor(self, db: Session):
        payment = RecurringPayment(
            merchant_pattern="x",
            name="X",
            expected_amount=-50.0,
            cadence="four_weekly",
            anchor_date=date(2025, 4, 1),
            status="confirmed",
        )
        db.add(payment)
        db.flush()
        assert next_expected_date(payment) == date(2025, 4, 29)


class TestImportTimeMatching:
    def test_import_matches_confirmed_pattern_and_appends_occurrence(self, client, db: Session):
        _seed_monthly_group(db, count=4, start=date(2025, 1, 15))
        client.post("/api/recurring/rescan")
        payment_id = client.get("/api/recurring").json()[0]["id"]
        client.post(f"/api/recurring/{payment_id}/confirm", json={})

        # Last occurrence was 2025-04-15 (i=3 -> 2025-01-15 + 90 days = 2025-04-15).
        # next_expected = one month later = 2025-05-15. Import a match near it.
        import csv
        import io

        from tests.conftest import make_transaction

        # Directly insert a new matching transaction and re-run matching via
        # the recurring service to avoid depending on CSV import plumbing.
        new_tx = make_transaction(
            db,
            bedrag=-12.99,
            naam="Netflix",
            merchant_name="Netflix",
            datum=date(2025, 5, 16),
            volgnummer="100",
        )
        db.commit()

        from app.services.recurring_detector import match_new_transactions

        matched = match_new_transactions(db, [new_tx])
        db.commit()

        assert matched == 1
        occ_resp = client.get(f"/api/recurring/{payment_id}/occurrences")
        assert len(occ_resp.json()) == 5

        updated = db.get(RecurringPayment, payment_id)
        assert updated.anchor_date == date(2025, 5, 16)

    def test_import_hook_runs_matching_end_to_end(self, client, db: Session):
        _seed_monthly_group(db, count=4, start=date(2025, 1, 15))
        client.post("/api/recurring/rescan")
        payment_id = client.get("/api/recurring").json()[0]["id"]
        client.post(f"/api/recurring/{payment_id}/confirm", json={})

        csv_content = _build_asn_csv(
            [
                {
                    "datum": "16-05-2025",
                    "rekening": "NL00TEST0000000001",
                    "tegenrekening": "",
                    "naam": "Netflix",
                    "bedrag": "-12,99",
                    "omschrijving": "Netflix subscription",
                    "volgnummer": "555",
                }
            ]
        )
        resp = client.post(
            "/api/transactions/import",
            files={"file": ("import.csv", csv_content, "text/csv")},
        )
        assert resp.status_code == 200

        occ_resp = client.get(f"/api/recurring/{payment_id}/occurrences")
        assert len(occ_resp.json()) == 5


class TestNotices:
    def test_amount_changed_notice(self, client, db: Session):
        _seed_monthly_group(db, count=4, amount=-12.99)
        client.post("/api/recurring/rescan")
        payment_id = client.get("/api/recurring").json()[0]["id"]
        client.post(f"/api/recurring/{payment_id}/confirm", json={})

        payment = db.get(RecurringPayment, payment_id)
        # Force a large deviation directly on the latest occurrence to
        # simulate an amount that changed since expected_amount was set.
        occurrences = db.query(RecurringPaymentOccurrence).filter_by(
            recurring_payment_id=payment_id
        ).all()
        latest = max(occurrences, key=lambda o: o.date)
        latest.amount = -20.0
        db.commit()

        resp = client.get("/api/recurring/notices")
        assert resp.status_code == 200
        notices = resp.json()
        assert any(n["type"] == "amount_changed" and n["recurring_payment_id"] == payment_id for n in notices)

    def test_possibly_missed_notice(self, client, db: Session):
        # Anchor far enough in the past that next_expected + grace has passed.
        old_start = date.today() - timedelta(days=200)
        _seed_monthly_group(db, count=4, start=old_start)
        client.post("/api/recurring/rescan")
        payment_id = client.get("/api/recurring").json()[0]["id"]
        client.post(f"/api/recurring/{payment_id}/confirm", json={})

        resp = client.get("/api/recurring/notices")
        assert resp.status_code == 200
        notices = resp.json()
        assert any(
            n["type"] == "possibly_missed" and n["recurring_payment_id"] == payment_id
            for n in notices
        )

    def test_no_notices_for_healthy_pattern(self, client, db: Session):
        # Anchor recent enough that next_expected hasn't passed yet.
        recent_start = date.today() - timedelta(days=60)
        _seed_monthly_group(db, count=4, start=recent_start)
        client.post("/api/recurring/rescan")
        payment_id = client.get("/api/recurring").json()[0]["id"]
        client.post(f"/api/recurring/{payment_id}/confirm", json={})

        resp = client.get("/api/recurring/notices")
        notices = [n for n in resp.json() if n["recurring_payment_id"] == payment_id]
        assert notices == []


def _build_asn_csv(rows: list[dict]) -> bytes:
    """Build a minimal ASN-format CSV matching the parser's expected header."""
    header = (
        "Boekingsdatum;Rekeningnummer;Tegenrekeningnummer;Naam tegenpartij;Adres;"
        "Postcode;Plaats;Valutasoort rekening;Saldo voor mutatie;Valutasoort mutatie;"
        "Transactiebedrag;Datum afschrijving;Valutadatum;Interne transactiecode;"
        "Globale transactiecode;Volgnummer transactie;Betalingskenmerk;Omschrijving;"
        "Afschriftnummer;Categorie"
    )
    lines = [header]
    for r in rows:
        lines.append(
            ";".join(
                [
                    r["datum"],
                    r["rekening"],
                    r.get("tegenrekening", ""),
                    r["naam"],
                    "",
                    "",
                    "",
                    "EUR",
                    "1000,00",
                    "EUR",
                    r["bedrag"],
                    r["datum"],
                    r["datum"],
                    "GT",
                    "BET",
                    r["volgnummer"],
                    "",
                    r["omschrijving"],
                    "1",
                    "Diversen",
                ]
            )
        )
    return ("\n".join(lines)).encode("utf-8")
