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
        # Every 28 days: day-of-month drifts steadily and, over enough
        # cycles, exceeds the +/-4 monthly stability tolerance for more
        # than 25% of the series (cadence rules v2 allow a 75% day-stable
        # fraction for monthly, not 100%, so this needs enough occurrences
        # for the drift to clearly beat that bar).
        start = date(2025, 1, 3)
        dates = [start + timedelta(days=28 * i) for i in range(9)]
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

    def test_erratic_series_with_matching_median_gap_is_not_four_weekly(self):
        # Genuinely erratic gaps (26, 30, 25, 29, 60, 15, 45): even with up
        # to 25% of gaps discounted as outliers, too many of the remaining
        # gaps fall outside both the monthly and four_weekly windows, and
        # the day-of-month (1, 27, 26, 23, 21, 20, 5, 19) isn't stable for
        # 75% of dates either. This must not be misclassified as a
        # recurring pattern: it's just noise.
        d0 = date(2025, 1, 1)
        d1 = d0 + timedelta(days=26)
        d2 = d1 + timedelta(days=30)
        d3 = d2 + timedelta(days=25)
        d4 = d3 + timedelta(days=29)
        d5 = d4 + timedelta(days=60)
        d6 = d5 + timedelta(days=15)
        d7 = d6 + timedelta(days=45)
        dates = [d0, d1, d2, d3, d4, d5, d6, d7]
        assert rd.detect_cadence(dates) is None


class TestDetectCadenceRealWorldPatterns:
    """Cadence rules v2, driven by real user data the old strict rules
    missed: outlier-tolerant gap classification and the monthly
    fixed-amount fallback (see spec "Recurring-payment detection",
    cadence rules v2)."""

    def test_anwb_wandering_day_fixed_amount_monthly(self):
        # Identical amounts, wandering collection day (spread far beyond
        # +/-4), gaps [27, 29, 30, 41, 22, 32, 30]: fails day-of-month
        # stability but qualifies monthly via the fixed-amount fallback.
        gaps = [27, 29, 30, 41, 22, 32, 30]
        dates = [date(2025, 1, 1)]
        for g in gaps:
            dates.append(dates[-1] + timedelta(days=g))
        amounts = [-10.70] * len(dates)

        result = rd.detect_cadence(dates, amounts)
        assert result is not None
        assert result.cadence == "monthly"

    def test_basic_fit_four_weekly_with_one_irregular_gap(self):
        # Mostly-28-day gaps with one irregular gap (10 days): outlier
        # tolerance drops the irregular gap and still calls four_weekly.
        gaps = [28, 28, 28, 10, 28, 28, 28, 28]
        dates = [date(2025, 1, 3)]
        for g in gaps:
            dates.append(dates[-1] + timedelta(days=g))
        amounts = [-24.99] * len(dates)

        result = rd.detect_cadence(dates, amounts)
        assert result is not None
        assert result.cadence == "four_weekly"

    def test_fbto_monthly_with_wandering_day_but_day_stable_enough(self):
        days = [26, 24, 24, 24, 24, 25, 24, 24, 24]
        dates = [date(2025, 1, days[0])]
        for i, d in enumerate(days[1:], start=2):
            year = 2025 + (i - 1) // 12
            month = (i - 1) % 12 + 1
            dates.append(date(year, month, d))
        amounts = [-151.0] * len(dates)

        result = rd.detect_cadence(dates, amounts)
        assert result is not None
        assert result.cadence == "monthly"

    def test_hollandsnieuwe_monthly_with_gaps_up_to_32(self):
        gaps = [28, 32, 29, 31, 30, 28, 29]
        dates = [date(2025, 1, 22)]
        for g in gaps:
            dates.append(dates[-1] + timedelta(days=g))
        amounts = [-10.33] * len(dates)

        result = rd.detect_cadence(dates, amounts)
        assert result is not None
        assert result.cadence == "monthly"

    def test_spotify_monthly_survives_gap_anomaly(self):
        dates = [date(2025, 1, 3) + timedelta(days=30 * i) for i in range(6)]
        amounts = [-3.00] * len(dates)

        result = rd.detect_cadence(dates, amounts)
        assert result is not None
        assert result.cadence == "monthly"


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

    def test_three_occurrences_two_within_tolerance_does_not_qualify(self):
        # 2 of 3 within 15% of median is 2/3 ~= 0.667, below the 75% bar.
        amounts = [-100.0, -101.0, -200.0]
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


class TestAmountClusteringRealWorldPatterns:
    """End-to-end `build_candidates` coverage for real user data the old
    detector missed entirely: a single counterparty/merchant can carry more
    than one recurring pattern, or one recurring pattern mixed with
    non-recurring noise, and amount clustering must separate them."""

    def test_nedap_salary_cluster_detected_despite_mixed_noise(self, db: Session):
        # Salary near day 22, monthly, with two adjacent bonus months
        # (holiday bonus + review payout) at a much higher amount, mixed
        # with scattered expense-claim reimbursements (small positive,
        # same IBAN) and scattered small debits (-5.50). Only the salary
        # cluster should surface as a candidate.
        iban = "NL02NEDAP000000001"
        start = date(2025, 1, 22)
        salary_amounts = [3109.48, 4073.78, 5034.83, 3166.17, 3252.34, 3227.34, 3166.17]
        for i, amount in enumerate(salary_amounts):
            make_transaction(
                db, bedrag=amount, naam="Nedap", tegenrekening=iban,
                datum=start + timedelta(days=30 * i), volgnummer=f"sal{i}",
            )
        claim_amounts = [31.96, 47.94, 52.59]
        claim_dates = [date(2025, 3, 5), date(2025, 6, 14), date(2025, 9, 2)]
        for i, (amount, d) in enumerate(zip(claim_amounts, claim_dates)):
            make_transaction(
                db, bedrag=amount, naam="Nedap", tegenrekening=iban, datum=d, volgnummer=f"claim{i}"
            )
        for i, d in enumerate([date(2025, 2, 3), date(2025, 4, 17), date(2025, 7, 9)]):
            make_transaction(
                db, bedrag=-5.50, naam="Nedap", tegenrekening=iban, datum=d, volgnummer=f"debit{i}"
            )

        from app.models import Transaction
        candidates = rd.build_candidates(db.query(Transaction).all())

        salary_candidates = [c for c in candidates if c.is_income and c.cadence == "monthly"]
        assert len(salary_candidates) == 1
        salary = salary_candidates[0]
        assert salary.expected_day in range(19, 26)
        assert 3100 <= salary.expected_amount <= 3300
        # The claim reimbursements and small debits never form a
        # confusingly "recurring" candidate of their own (too few
        # occurrences, non-periodic).
        assert not any(c.is_income and c is not salary for c in candidates)
        assert not any(not c.is_income for c in candidates)

    def test_fbto_claim_cluster_separated_from_recurring_premium(self, db: Session):
        # Recurring -151.00 premium, monthly, mixed with scattered claim
        # payouts of very different (also negative) amounts.
        iban = "NL01FBTO0000000001"
        days = [26, 24, 24, 24, 24, 25, 24, 24, 24]
        for i, day in enumerate(days):
            year = 2025 + i // 12
            month = i % 12 + 1
            make_transaction(
                db, bedrag=-151.0, naam="FBTO", tegenrekening=iban,
                datum=date(year, month, day), volgnummer=f"prem{i}",
            )
        claim_amounts = [-24.16, -214.74, -103.75]
        claim_dates = [date(2025, 2, 10), date(2025, 5, 3), date(2025, 8, 19)]
        for i, (amount, d) in enumerate(zip(claim_amounts, claim_dates)):
            make_transaction(
                db, bedrag=amount, naam="FBTO", tegenrekening=iban, datum=d, volgnummer=f"claim{i}"
            )

        from app.models import Transaction
        candidates = rd.build_candidates(db.query(Transaction).all())

        assert len(candidates) == 1
        assert candidates[0].expected_amount == -151.0
        assert candidates[0].cadence == "monthly"

    def test_hollandsnieuwe_cluster_separated_from_topups(self, db: Session):
        iban = "NL03HOLL0000000001"
        gaps = [28, 32, 29, 31, 30, 28, 29]
        d = date(2025, 1, 22)
        dates = [d]
        for g in gaps:
            d = d + timedelta(days=g)
            dates.append(d)
        for i, dd in enumerate(dates):
            make_transaction(
                db, bedrag=-10.33, naam="HollandsNieuwe", tegenrekening=iban, datum=dd, volgnummer=f"m{i}"
            )
        for i, dd in enumerate([date(2025, 2, 5), date(2025, 2, 7), date(2025, 2, 9)]):
            make_transaction(
                db, bedrag=-5.00, naam="HollandsNieuwe", tegenrekening=iban, datum=dd, volgnummer=f"top{i}"
            )
        make_transaction(
            db, bedrag=-20.00, naam="HollandsNieuwe", tegenrekening=iban, datum=date(2025, 5, 1), volgnummer="big"
        )

        from app.models import Transaction
        candidates = rd.build_candidates(db.query(Transaction).all())

        matching = [c for c in candidates if c.expected_amount == -10.33]
        assert len(matching) == 1
        assert matching[0].cadence == "monthly"

    def test_basic_fit_four_weekly_separated_from_outlier_row(self, db: Session):
        iban = "NL04BASF0000000001"
        gaps = [28, 28, 28, 10, 28, 28, 28, 28]
        d = date(2025, 1, 3)
        dates = [d]
        for g in gaps:
            d = d + timedelta(days=g)
            dates.append(d)
        for i, dd in enumerate(dates):
            make_transaction(
                db, bedrag=-24.99, naam="Basic-Fit", tegenrekening=iban, datum=dd, volgnummer=f"m{i}"
            )
        make_transaction(
            db, bedrag=-20.00, naam="Basic-Fit", tegenrekening=iban, datum=date(2025, 4, 15), volgnummer="outlier"
        )

        from app.models import Transaction
        candidates = rd.build_candidates(db.query(Transaction).all())

        matching = [c for c in candidates if c.expected_amount == -24.99]
        assert len(matching) == 1
        assert matching[0].cadence == "four_weekly"

    def test_anwb_wandering_day_detected_via_amount_fallback(self, db: Session):
        iban = "NL05ANWB0000000001"
        gaps = [27, 29, 30, 41, 22, 32, 30]
        d = date(2025, 1, 1)
        dates = [d]
        for g in gaps:
            d = d + timedelta(days=g)
            dates.append(d)
        for i, dd in enumerate(dates):
            make_transaction(
                db, bedrag=-10.70, naam="ANWB", tegenrekening=iban, datum=dd, volgnummer=f"m{i}"
            )

        from app.models import Transaction
        candidates = rd.build_candidates(db.query(Transaction).all())

        assert len(candidates) == 1
        assert candidates[0].cadence == "monthly"
        assert candidates[0].expected_amount == -10.70

    def test_spotify_monthly_survives_unrelated_large_transfer_same_person(self, db: Session):
        dates = [date(2025, 1, 3) + timedelta(days=30 * i) for i in range(6)]
        for i, d in enumerate(dates):
            make_transaction(db, bedrag=-3.00, naam="M. Hameter", datum=d, volgnummer=f"sub{i}")
        # An unrelated, much larger transfer to the same person shortly
        # after the first subscription payment must not disrupt detection.
        make_transaction(
            db, bedrag=-398.63, naam="M. Hameter", datum=date(2025, 1, 6), volgnummer="transfer"
        )

        from app.models import Transaction
        candidates = rd.build_candidates(db.query(Transaction).all())

        matching = [c for c in candidates if c.expected_amount == -3.0]
        assert len(matching) == 1
        assert matching[0].cadence == "monthly"


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

    def test_stale_suggested_row_removed_when_group_key_changes(self, db: Session):
        # First run: merchant normalizes to "spotify".
        dates = [date(2025, 1, 5), date(2025, 2, 5), date(2025, 3, 6)]
        txs = [
            make_transaction(db, bedrag=-9.99, naam=None, merchant_name="Spotify 123", datum=d)
            for d in dates
        ]
        from app.models import Transaction
        candidates_first = rd.build_candidates(db.query(Transaction).all())
        rows_first = rd.upsert_recurring_payments(db, candidates_first)
        db.flush()
        assert len(rows_first) == 1
        assert rows_first[0].merchant_pattern == "spotify"

        # Second run: every historical transaction in the group is renamed
        # (e.g. the merchant rebranded), so the group key changes to
        # "spotify premium". The old "spotify" key no longer appears in the
        # latest detection and should be cleaned up since it was only ever
        # suggested (never confirmed/dismissed).
        for tx in txs:
            tx.merchant_name = "Spotify Premium 456"
        db.flush()
        candidates_second = rd.build_candidates(db.query(Transaction).all())
        rows_second = rd.upsert_recurring_payments(db, candidates_second)
        db.flush()

        new_keys = {r.merchant_pattern for r in rows_second}
        assert "spotify premium" in new_keys

        # Exactly one row remains for this merchant lineage, and it carries
        # the new key, not the old one. (Not asserting on stale_id directly:
        # SQLite may reuse a deleted row's integer id for the next insert,
        # so id equality alone can't distinguish "same row kept" from
        # "old row deleted, new row happens to get the same id".)
        all_rows = db.query(RecurringPayment).all()
        assert len(all_rows) == 1
        assert all(r.merchant_pattern != "spotify" for r in all_rows)

    def test_stale_confirmed_row_not_removed_when_group_key_vanishes(self, db: Session):
        confirmed = RecurringPayment(
            merchant_pattern="oldgym",
            counterparty_iban=None,
            name="Old Gym",
            expected_amount=-30.0,
            cadence="monthly",
            expected_day=1,
            anchor_date=date(2024, 12, 1),
            status="confirmed",
            is_income=False,
        )
        db.add(confirmed)
        db.flush()
        confirmed_id = confirmed.id

        # No current transactions produce the "oldgym" group key at all.
        candidates = rd.build_candidates([])
        rd.upsert_recurring_payments(db, candidates)
        db.flush()

        still_there = db.query(RecurringPayment).filter_by(id=confirmed_id).one_or_none()
        assert still_there is not None
        assert still_there.status == "confirmed"
