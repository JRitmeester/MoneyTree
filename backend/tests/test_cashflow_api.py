"""API-level tests for the cash-flow calendar and transfer advisor
endpoints and the buffer_pct settings.

See docs/superpowers/specs/2026-08-27-financial-insights-design.md, section
"Cash-flow calendar and transfer advisor".
"""
from datetime import date

from sqlalchemy.orm import Session

from app.models import AppSetting, RecurringPayment, RecurringPaymentOccurrence

from .conftest import make_transaction


def _confirmed(
    db: Session,
    *,
    name: str,
    expected_amount: float,
    cadence: str,
    expected_day: int | None,
    anchor_date: date,
    is_income: bool = False,
) -> RecurringPayment:
    payment = RecurringPayment(
        merchant_pattern=name,
        name=name,
        expected_amount=expected_amount,
        cadence=cadence,
        expected_day=expected_day,
        anchor_date=anchor_date,
        status="confirmed",
        is_income=is_income,
    )
    db.add(payment)
    db.flush()
    if is_income:
        tx = make_transaction(db, bedrag=expected_amount, datum=anchor_date, naam=name)
        db.add(
            RecurringPaymentOccurrence(
                recurring_payment_id=payment.id, transaction_id=tx.id,
                amount=expected_amount, date=anchor_date,
            )
        )
    db.commit()
    db.refresh(payment)
    return payment


class TestCalendarEndpoint:
    def test_invalid_month_format_rejected(self, client, db: Session):
        resp = client.get("/api/cashflow/calendar?month=2026-8")
        assert resp.status_code == 400

    def test_projects_confirmed_payments_into_month(self, client, db: Session):
        _confirmed(
            db, name="Rent", expected_amount=-900, cadence="monthly",
            expected_day=1, anchor_date=date(2026, 7, 1),
        )
        resp = client.get("/api/cashflow/calendar?month=2026-08")
        assert resp.status_code == 200
        body = resp.json()
        assert body["month"] == "2026-08"
        dates = [d["date"] for d in body["days"]]
        # 2026-08-01 is a Saturday; shifted to the next business day.
        assert "2026-08-03" in dates

    def test_salary_day_flagged(self, client, db: Session):
        salary = _confirmed(
            db, name="Salary", expected_amount=3000, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 7, 22), is_income=True,
        )
        resp = client.get("/api/cashflow/calendar?month=2026-08")
        body = resp.json()
        day = next(d for d in body["days"] if d["date"] == "2026-08-24")
        item = next(i for i in day["items"] if i["recurring_payment_id"] == salary.id)
        assert item["is_salary"] is True


class TestAdviceEndpoint:
    def test_no_salary_returns_explicit_state(self, client, db: Session):
        resp = client.get("/api/cashflow/advice")
        assert resp.status_code == 200
        body = resp.json()
        assert body["salary_confirmed"] is False
        assert body["message"] == "Confirm your salary as recurring income first"

    def test_advice_uses_persisted_buffer_pct(self, client, db: Session):
        _confirmed(
            db, name="Salary", expected_amount=3000, cadence="monthly",
            expected_day=22, anchor_date=date(2026, 7, 22), is_income=True,
        )
        resp = client.put("/api/cashflow/settings", json={"buffer_pct": 20})
        assert resp.status_code == 200
        assert resp.json()["buffer_pct"] == 20

        resp = client.get("/api/cashflow/advice")
        assert resp.status_code == 200
        assert resp.json()["buffer_pct"] == 20


class TestSettingsEndpoint:
    def test_default_buffer_pct(self, client, db: Session):
        resp = client.get("/api/cashflow/settings")
        assert resp.status_code == 200
        assert resp.json()["buffer_pct"] == 10.0

    def test_update_persists(self, client, db: Session):
        resp = client.put("/api/cashflow/settings", json={"buffer_pct": 15})
        assert resp.status_code == 200
        row = db.get(AppSetting, "buffer_pct")
        assert row is not None
        assert float(row.value) == 15.0

    def test_update_rejects_out_of_range(self, client, db: Session):
        resp = client.put("/api/cashflow/settings", json={"buffer_pct": 150})
        assert resp.status_code == 422
