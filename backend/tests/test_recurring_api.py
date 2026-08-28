"""Tests for the recurring-payment lifecycle API: list/confirm/dismiss/patch,
rescan, occurrences, import-time matching, and notices.

See docs/superpowers/specs/2026-08-27-financial-insights-design.md,
"Recurring-payment detection" Lifecycle paragraph.
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import AppSetting, RecurringPayment, RecurringPaymentOccurrence, Transaction
from app.services.recurring_detector import (
    MATCH_WIDE_BAND,
    detect_recurring_payments,
    match_new_transactions,
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

    def test_list_carries_occurrence_count_and_last_seen(self, client, db: Session):
        dates = _monthly_dates(date(2025, 1, 15), 4)
        _seed_monthly_group(db, count=4)
        client.post("/api/recurring/rescan")
        payment_id = client.get("/api/recurring").json()[0]["id"]
        client.post(f"/api/recurring/{payment_id}/confirm", json={})

        resp = client.get("/api/recurring", params={"status": "confirmed"})
        assert resp.status_code == 200
        body = resp.json()[0]
        assert body["occurrence_count"] == 4
        assert body["last_seen"] == dates[-1].isoformat()

    def test_list_suggested_rows_also_carry_occurrence_aggregates(self, client, db: Session):
        dates = _monthly_dates(date(2025, 1, 15), 4)
        _seed_monthly_group(db, count=4)
        client.post("/api/recurring/rescan")

        resp = client.get("/api/recurring", params={"status": "suggested"})
        body = resp.json()[0]
        assert body["occurrence_count"] == 4
        assert body["last_seen"] == dates[-1].isoformat()


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


class TestShiftAwareMatching:
    """Controller ruling: match_new_transactions must anchor its
    +/-DATE_MATCH_WINDOW_DAYS window on the same shift-aware expected date
    the calendar/advisor use (`shift_expected_date`), not the raw calendar
    date, since that's the day the payment actually lands."""

    def test_income_matches_on_backward_shifted_date_across_holiday_weekend(self, db: Session):
        # Easter Sunday 2008-03-23 falls on the 23rd: raw next_expected for
        # a salary expected on day 23 lands on that Sunday. Income shifts
        # backward: 23rd Sun -> 22nd Sat -> 21st Fri (Good Friday, an NL
        # holiday) -> 20th Thu (the actual banking day).
        payment = RecurringPayment(
            merchant_pattern="",
            counterparty_iban="NL06SALARY000000001",
            name="Salary",
            expected_amount=3000.0,
            cadence="monthly",
            expected_day=23,
            anchor_date=date(2008, 2, 23),
            status="confirmed",
            is_income=True,
        )
        db.add(payment)
        db.flush()

        # Raw expected is 2008-03-23; 2008-03-16 is 7 days before that (
        # outside the +/-5 day window measured from the raw date) but only
        # 4 days before the shifted banking day 2008-03-20 (inside the
        # window measured from the shifted date).
        tx = make_transaction(
            db, bedrag=3000.0, naam="Employer", tegenrekening="NL06SALARY000000001",
            datum=date(2008, 3, 16), volgnummer="shifted1",
        )
        db.commit()

        matched = match_new_transactions(db, [tx])
        db.commit()

        assert matched == 1
        db.refresh(payment)
        assert payment.anchor_date == date(2008, 3, 16)
        occurrences = db.query(RecurringPaymentOccurrence).filter_by(
            recurring_payment_id=payment.id
        ).all()
        assert any(o.transaction_id == tx.id for o in occurrences)


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


def _seed_iban_monthly_group(
    db: Session, iban: str, count: int = 4, amount: float = -1000.0, start: date = date(2025, 1, 1)
) -> None:
    for i in range(count):
        d = _add_months_test_helper(start, i)
        make_transaction(
            db,
            bedrag=amount,
            naam="Landlord",
            tegenrekening=iban,
            datum=d,
            volgnummer=f"iban{i + 1}",
        )
    db.commit()


def _add_months_test_helper(base: date, months: int) -> date:
    month_index = base.month - 1 + months
    year = base.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, base.day)


class TestTwoBandMatching:
    """Spec-owner ruling 2026-08-28: matching accepts a wide band (50%) of
    expected_amount; within tolerance but outside the wide band it does not
    match at all; inside the wide band but outside amount_tolerance it
    matches and raises an amount_changed notice."""

    def _confirmed_payment(self, client, db: Session, iban: str = "NL01BANK0123456789") -> int:
        _seed_iban_monthly_group(db, iban)
        client.post("/api/recurring/rescan")
        payments = client.get("/api/recurring").json()
        payment_id = next(p["id"] for p in payments if p["counterparty_iban"] == iban)
        client.post(f"/api/recurring/{payment_id}/confirm", json={})
        return payment_id

    def test_far_outlier_does_not_match(self, client, db: Session):
        iban = "NL01BANK0123456789"
        payment_id = self._confirmed_payment(client, db, iban)
        before = len(client.get(f"/api/recurring/{payment_id}/occurrences").json())

        payment = db.get(RecurringPayment, payment_id)
        expected_date = next_expected_date(payment)
        far_tx = make_transaction(
            db, bedrag=-3000.0, naam="Landlord", tegenrekening=iban, datum=expected_date, volgnummer="far"
        )
        db.commit()

        matched = match_new_transactions(db, [far_tx])
        db.commit()

        assert matched == 0
        after = len(client.get(f"/api/recurring/{payment_id}/occurrences").json())
        assert after == before

    def test_wide_band_deviation_matches_and_notices(self, client, db: Session):
        iban = "NL01BANK0123456789"
        payment_id = self._confirmed_payment(client, db, iban)
        before = len(client.get(f"/api/recurring/{payment_id}/occurrences").json())

        payment = db.get(RecurringPayment, payment_id)
        expected_date = next_expected_date(payment)
        deviated_tx = make_transaction(
            db, bedrag=-1200.0, naam="Landlord", tegenrekening=iban, datum=expected_date, volgnummer="dev"
        )
        db.commit()

        matched = match_new_transactions(db, [deviated_tx])
        db.commit()

        assert matched == 1
        after = len(client.get(f"/api/recurring/{payment_id}/occurrences").json())
        assert after == before + 1

        notices = client.get("/api/recurring/notices").json()
        assert any(n["type"] == "amount_changed" and n["recurring_payment_id"] == payment_id for n in notices)


class TestDriftCannotMaskNotices:
    """Spec-owner ruling 2026-08-28: drift only applies within
    amount_tolerance; after CONSECUTIVE_SNAP_COUNT (3) consecutive
    out-of-tolerance occurrences on the same side, expected_amount snaps to
    their median, clearing the notice."""

    def test_sustained_increase_notices_twice_then_snaps(self, client, db: Session):
        iban = "NL02BANK0987654321"
        _seed_iban_monthly_group(db, iban, count=4, amount=-1000.0, start=date(2025, 1, 1))
        client.post("/api/recurring/rescan")
        payments = client.get("/api/recurring").json()
        payment_id = next(p["id"] for p in payments if p["counterparty_iban"] == iban)
        client.post(f"/api/recurring/{payment_id}/confirm", json={})

        raised_amount = -1160.0  # +16%, outside 15% tolerance, inside 50% wide band

        for i in range(3):
            payment = db.get(RecurringPayment, payment_id)
            expected_date = next_expected_date(payment)
            tx = make_transaction(
                db,
                bedrag=raised_amount,
                naam="Landlord",
                tegenrekening=iban,
                datum=expected_date,
                volgnummer=f"raise{i}",
            )
            db.commit()
            matched = match_new_transactions(db, [tx])
            db.commit()
            assert matched == 1

            payment = db.get(RecurringPayment, payment_id)
            notices = [
                n
                for n in client.get("/api/recurring/notices").json()
                if n["recurring_payment_id"] == payment_id and n["type"] == "amount_changed"
            ]

            if i < 2:
                assert payment.expected_amount == -1000.0
                assert notices, f"expected an amount_changed notice after occurrence {i + 1}"
            else:
                assert payment.expected_amount == -1160.0
                assert notices == []


class TestUpsertGroupKeyCollisionGuard:
    def test_confirmed_key_reappearing_creates_no_duplicate_suggested_row(self, client, db: Session):
        _seed_monthly_group(db, count=4)
        client.post("/api/recurring/rescan")
        payment_id = client.get("/api/recurring").json()[0]["id"]
        client.post(f"/api/recurring/{payment_id}/confirm", json={})

        # A further import of the same group should not create a new
        # suggested row for a key already owned by a confirmed row.
        _run_detector(db)

        all_payments = client.get("/api/recurring").json()
        assert len(all_payments) == 1
        assert all_payments[0]["status"] == "confirmed"
        suggested = client.get("/api/recurring", params={"status": "suggested"}).json()
        assert suggested == []


class TestNextExpectedDateClamping:
    def test_day_31_clamps_to_february_28(self, db: Session):
        payment = RecurringPayment(
            merchant_pattern="rent",
            name="Rent",
            expected_amount=-1000.0,
            cadence="monthly",
            expected_day=31,
            anchor_date=date(2025, 1, 31),
            status="confirmed",
        )
        db.add(payment)
        db.flush()
        assert next_expected_date(payment) == date(2025, 2, 28)


class TestPossiblyMissedBoundary:
    def test_exactly_five_days_past_fires(self, db: Session):
        today = date(2026, 1, 15)
        anchor = today - timedelta(days=28 + 5)
        payment = RecurringPayment(
            merchant_pattern="x",
            name="X",
            expected_amount=-50.0,
            cadence="four_weekly",
            anchor_date=anchor,
            status="confirmed",
        )
        db.add(payment)
        db.flush()

        from app.services.recurring_detector import compute_notices

        notices = compute_notices(db, today=today)
        assert any(n["type"] == "possibly_missed" and n["recurring_payment_id"] == payment.id for n in notices)

    def test_four_days_past_does_not_fire(self, db: Session):
        today = date(2026, 1, 15)
        anchor = today - timedelta(days=28 + 4)
        payment = RecurringPayment(
            merchant_pattern="y",
            name="Y",
            expected_amount=-50.0,
            cadence="four_weekly",
            anchor_date=anchor,
            status="confirmed",
        )
        db.add(payment)
        db.flush()

        from app.services.recurring_detector import compute_notices

        notices = compute_notices(db, today=today)
        assert not any(n["type"] == "possibly_missed" and n["recurring_payment_id"] == payment.id for n in notices)


class TestDeleteEverythingWipesRecurringTables:
    def test_delete_everything_clears_recurring_tables(self, client, db: Session):
        _seed_monthly_group(db, count=4)
        client.post("/api/recurring/rescan")
        payment_id = client.get("/api/recurring").json()[0]["id"]
        client.post(f"/api/recurring/{payment_id}/confirm", json={})

        # Seed an AppSetting to verify it gets wiped
        setting = AppSetting(key="buffer_pct", value="15.0")
        db.add(setting)
        db.commit()

        assert db.query(RecurringPayment).count() > 0
        assert db.query(RecurringPaymentOccurrence).count() > 0
        assert db.query(AppSetting).count() == 1

        resp = client.delete("/api/settings/everything")
        assert resp.status_code == 200

        assert db.query(RecurringPayment).count() == 0
        assert db.query(RecurringPaymentOccurrence).count() == 0
        assert db.query(AppSetting).count() == 0


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
