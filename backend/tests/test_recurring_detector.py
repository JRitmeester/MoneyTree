"""Tests for the recurring-payment detector service.

Covers grouping, cadence classification (monthly / four_weekly / yearly),
the amount-qualifying rule with non-disqualifying outliers, and the
suggested-only upsert lifecycle.
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import RecurringPayment, RecurringPaymentOccurrence
from app.services import recurring_detector as rd
from tests.conftest import make_transaction


def _monthly_dates(start: date, count: int, day_drift: int = 0) -> list[date]:
    """count monthly dates, ~30 days apart, day-of-month optionally drifting
    a little each month (still within the +/-4 stability tolerance)."""
    dates = []
    for i in range(count):
        d = start + timedelta(days=30 * i) + timedelta(days=day_drift * i)
        dates.append(d)
    return dates


class TestDetectCadence:
    def test_monthly_stable_day(self):
        dates = [date(2025, 1, 15), date(2025, 2, 15), date(2025, 3, 16), date(2025, 4, 14)]
        result = rd.detect_cadence(dates)
        assert result is not None
        assert result.cadence == "monthly"
        assert result.expected_day in (14, 15, 16)
        assert result.anchor_date == dates[-1]

    def test_four_weekly_drift_basic_fit_pattern(self):
        # Every 28 days: day-of-month drifts steadily and exceeds the +/-4
        # monthly stability tolerance across the series.
        start = date(2025, 1, 3)
        dates = [start + timedelta(days=28 * i) for i in range(5)]
        result = rd.detect_cadence(dates)
        assert result is not None
        assert result.cadence == "four_weekly"
        assert result.expected_day is None
        assert result.anchor_date == dates[-1]

    def test_yearly_two_occurrences(self):
        dates = [date(2024, 6, 1), date(2025, 6, 5)]
        result = rd.detect_cadence(dates)
        assert result is not None
        assert result.cadence == "yearly"
        assert result.anchor_date == dates[-1]

    def test_too_few_occurrences_not_a_candidate(self):
        dates = [date(2025, 1, 15), date(2025, 2, 15)]
        assert rd.detect_cadence(dates) is None

    def test_irregular_gaps_not_a_candidate(self):
        dates = [date(2025, 1, 1), date(2025, 1, 10), date(2025, 3, 1), date(2025, 6, 1)]
        assert rd.detect_cadence(dates) is None


class TestAmountsQualify:
    def test_all_amounts_within_tolerance_qualify(self):
        assert rd.amounts_qualify([100.0, 102.0, 98.0, 101.0]) is True

    def test_settlement_outlier_does_not_disqualify_group(self):
        # 5 of 6 within 15% of median; the settlement-month outlier flags
        # but doesn't disqualify the whole group.
        amounts = [-120.0, -120.0, -115.0, -125.0, -45.0, -118.0]
        assert rd.amounts_qualify(amounts) is True
        median = rd.median_amount(amounts)
        assert rd.is_amount_outlier(-45.0, median, rd.AMOUNT_TOLERANCE_FRACTION) is True
        assert rd.is_amount_outlier(-118.0, median, rd.AMOUNT_TOLERANCE_FRACTION) is False

    def test_rent_increase_still_qualifies_as_one_candidate(self):
        # Rent goes up once; the group as a whole still qualifies.
        amounts = [-700.0, -700.0, -700.0, -750.0]
        assert rd.amounts_qualify(amounts) is True

    def test_too_many_outliers_disqualify(self):
        amounts = [-100.0, -200.0, -50.0, -300.0]
        assert rd.amounts_qualify(amounts) is False


class TestBuildCandidates:
    def test_groups_by_counterparty_iban_over_merchant(self, db: Session):
        dates = [date(2025, 1, 15), date(2025, 2, 15), date(2025, 3, 15)]
        for d in dates:
            make_transaction(
                db, bedrag=-15.0, naam="Netflix", tegenrekening="NL01ABNA0000000001", datum=d
            )
        from app.models import Transaction
        candidates = rd.build_candidates(db.query(Transaction).all())
        assert len(candidates) == 1
        assert candidates[0].counterparty_iban == "NL01ABNA0000000001"
        assert candidates[0].cadence == "monthly"

    def test_excludes_internal_transfers(self, db: Session):
        dates = [date(2025, 1, 15), date(2025, 2, 15), date(2025, 3, 15)]
        for d in dates:
            tx = make_transaction(
                db, bedrag=-500.0, naam="Savings", tegenrekening="NL02SAVE0000000002", datum=d
            )
            tx.is_internal_transfer = True
        db.flush()
        from app.models import Transaction
        candidates = rd.build_candidates(db.query(Transaction).all())
        assert candidates == []

    def test_salary_detected_as_recurring_income(self, db: Session):
        dates = [date(2025, 1, 25), date(2025, 2, 25), date(2025, 3, 25), date(2025, 4, 25)]
        for d in dates:
            make_transaction(
                db,
                bedrag=2500.0,
                naam="Employer BV",
                tegenrekening="NL03EMPL0000000003",
                datum=d,
            )
        from app.models import Transaction
        candidates = rd.build_candidates(db.query(Transaction).all())
        assert len(candidates) == 1
        assert candidates[0].is_income is True
        assert candidates[0].cadence == "monthly"

    def test_merchant_grouping_without_iban(self, db: Session):
        dates = [date(2025, 1, 5), date(2025, 2, 5), date(2025, 3, 6)]
        for d in dates:
            make_transaction(
                db, bedrag=-9.99, naam=None, merchant_name="Spotify 123", datum=d
            )
        from app.models import Transaction
        candidates = rd.build_candidates(db.query(Transaction).all())
        assert len(candidates) == 1
        assert candidates[0].merchant_pattern == "spotify"


class TestUpsertRecurringPayments:
    def test_creates_suggested_row_with_occurrences(self, db: Session):
        dates = [date(2025, 1, 15), date(2025, 2, 15), date(2025, 3, 15)]
        for d in dates:
            make_transaction(
                db, bedrag=-15.0, naam="Netflix", tegenrekening="NL01ABNA0000000001", datum=d
            )
        from app.models import Transaction
        candidates = rd.build_candidates(db.query(Transaction).all())
        rows = rd.upsert_recurring_payments(db, candidates)
        db.flush()
        assert len(rows) == 1
        assert rows[0].status == "suggested"
        occurrences = db.query(RecurringPaymentOccurrence).filter_by(
            recurring_payment_id=rows[0].id
        ).all()
        assert len(occurrences) == 3

    def test_never_touches_confirmed_row(self, db: Session):
        confirmed = RecurringPayment(
            merchant_pattern="",
            counterparty_iban="NL01ABNA0000000001",
            name="Netflix (manual name)",
            expected_amount=-13.0,
            cadence="monthly",
            expected_day=15,
            anchor_date=date(2024, 12, 15),
            status="confirmed",
            is_income=False,
        )
        db.add(confirmed)
        db.flush()

        dates = [date(2025, 1, 15), date(2025, 2, 15), date(2025, 3, 15)]
        for d in dates:
            make_transaction(
                db, bedrag=-15.0, naam="Netflix", tegenrekening="NL01ABNA0000000001", datum=d
            )
        from app.models import Transaction
        candidates = rd.build_candidates(db.query(Transaction).all())
        rd.upsert_recurring_payments(db, candidates)
        db.flush()

        db.refresh(confirmed)
        assert confirmed.status == "confirmed"
        assert confirmed.expected_amount == -13.0
        assert confirmed.name == "Netflix (manual name)"
        # No duplicate suggested row was created for the same group key.
        all_rows = db.query(RecurringPayment).filter_by(
            counterparty_iban="NL01ABNA0000000001"
        ).all()
        assert len(all_rows) == 1

    def test_never_touches_dismissed_row(self, db: Session):
        dismissed = RecurringPayment(
            merchant_pattern="spotify",
            counterparty_iban=None,
            name="Spotify",
            expected_amount=-9.99,
            cadence="monthly",
            expected_day=5,
            anchor_date=date(2024, 12, 5),
            status="dismissed",
            is_income=False,
        )
        db.add(dismissed)
        db.flush()

        dates = [date(2025, 1, 5), date(2025, 2, 5), date(2025, 3, 6)]
        for d in dates:
            make_transaction(db, bedrag=-9.99, naam=None, merchant_name="Spotify 123", datum=d)
        from app.models import Transaction
        candidates = rd.build_candidates(db.query(Transaction).all())
        rd.upsert_recurring_payments(db, candidates)
        db.flush()

        db.refresh(dismissed)
        assert dismissed.status == "dismissed"
        all_rows = db.query(RecurringPayment).filter_by(merchant_pattern="spotify").all()
        assert len(all_rows) == 1

    def test_refreshes_existing_suggested_row_in_place(self, db: Session):
        dates = [date(2025, 1, 15), date(2025, 2, 15), date(2025, 3, 15)]
        for d in dates:
            make_transaction(
                db, bedrag=-15.0, naam="Netflix", tegenrekening="NL01ABNA0000000001", datum=d
            )
        from app.models import Transaction
        candidates = rd.build_candidates(db.query(Transaction).all())
        rows_first = rd.upsert_recurring_payments(db, candidates)
        db.flush()
        first_id = rows_first[0].id

        make_transaction(
            db, bedrag=-16.0, naam="Netflix", tegenrekening="NL01ABNA0000000001",
            datum=date(2025, 4, 15),
        )
        candidates2 = rd.build_candidates(db.query(Transaction).all())
        rows_second = rd.upsert_recurring_payments(db, candidates2)
        db.flush()

        assert len(rows_second) == 1
        assert rows_second[0].id == first_id
        occurrences = db.query(RecurringPaymentOccurrence).filter_by(
            recurring_payment_id=first_id
        ).all()
        assert len(occurrences) == 4
        all_rows = db.query(RecurringPayment).all()
        assert len(all_rows) == 1
