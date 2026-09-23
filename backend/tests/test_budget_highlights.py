"""Tests for the deterministic budget highlights engine.

Spec: .superpowers/sdd/2026-09-23-budget-highlights/spec.md (binding),
task-2-brief.md.
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import Budget, BudgetLine, Category, IncidentalLabel, LineItem, Receipt
from app.services.budget_highlights import (
    BILL_INCREASE_FACTOR,
    ONE_OFF_FRACTION,
    OVERRUN_MIN_EUR,
    OVERRUN_PCT,
    SALARY_CHANGE_PCT,
    TOP_EXPENSES_COUNT,
    UNDERRUN_FRACTION,
    compute_highlights,
)

from .conftest import make_transaction

START = date(2026, 8, 21)
END = date(2026, 9, 23)  # half-open: END itself belongs to the next period


def _budget(db: Session, start: date = START, end: date = END) -> Budget:
    budget = Budget(start_date=start, end_date=end)
    db.add(budget)
    db.commit()
    return budget


def _category(
    db: Session, name: str, *, category_type: str = "expense", is_fixed: bool = False,
    parent_id: int | None = None,
) -> Category:
    cat = Category(name=name, category_type=category_type, is_fixed=is_fixed, parent_id=parent_id)
    db.add(cat)
    db.commit()
    return cat


def _line(db: Session, budget: Budget, category: Category, amount: float, *, source: str = "manual") -> BudgetLine:
    line = BudgetLine(budget_id=budget.id, category_id=category.id, amount=amount, source=source)
    db.add(line)
    db.commit()
    return line


def _highlights_for(result, rule: str):
    return [h for h in result.highlights if h.rule == rule]


class TestR1Normalization:
    def test_raw_net_excludes_savings_actual_from_consumption(self, db: Session):
        income = _category(db, "Salaris", category_type="income")
        groceries = _category(db, "Boodschappen")
        pot = _category(db, "Vakantiepot", category_type="savings")
        budget = _budget(db)
        _line(db, budget, income, 3000.0)
        _line(db, budget, groceries, 400.0)
        _line(db, budget, pot, 100.0)
        make_transaction(db, bedrag=3000.0, category_id=income.id, datum=START)
        make_transaction(db, bedrag=-350.0, category_id=groceries.id, datum=START)
        tx = make_transaction(db, bedrag=-100.0, category_id=pot.id, datum=START)
        tx.is_internal_transfer = True
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))

        # raw_net = income (3000) - consumption (350 groceries only, savings excluded)
        assert result.summary.raw_net == 2650.0

    def test_incidental_labeled_and_unlabeled_and_income_net_correctly(self, db: Session):
        cat = _category(db, "Vakantie kosten")
        label = IncidentalLabel(name="Vakantie")
        db.add(label)
        db.commit()
        budget = _budget(db)
        _line(db, budget, cat, 500.0)

        labeled_expense = make_transaction(db, bedrag=-600.0, category_id=cat.id, datum=START, is_incidental=True)
        labeled_expense.incidental_label_id = label.id

        refund = make_transaction(db, bedrag=32.80, category_id=cat.id, datum=START, is_incidental=True)
        refund.incidental_label_id = label.id

        make_transaction(db, bedrag=-800.0, category_id=cat.id, datum=START, is_incidental=True)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))

        by_label = {e.label: e.amount for e in result.summary.incidental_by_label}
        assert by_label["Vakantie"] == 567.20  # 600 - 32.80
        assert result.summary.unlabeled_incidental == 800.0
        assert result.summary.incidental_total == 1367.20

    def test_structural_net_adds_back_incidental_total(self, db: Session):
        income = _category(db, "Salaris", category_type="income")
        cat = _category(db, "Vakantie kosten")
        budget = _budget(db)
        _line(db, budget, income, 3000.0)
        _line(db, budget, cat, 0.0)
        make_transaction(db, bedrag=3000.0, category_id=income.id, datum=START)
        make_transaction(db, bedrag=-500.0, category_id=cat.id, datum=START, is_incidental=True)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))

        assert result.summary.raw_net == 2500.0
        assert result.summary.incidental_total == 500.0
        assert result.summary.structural_net == 3000.0

    def test_incidental_total_equals_sum_of_displayed_breakdown(self, db: Session):
        """Regression: incidental_total must equal the sum of the exact
        (already-rounded) parts shown in the breakdown, labeled and
        unlabeled alike. Rounding the label total (round(100.005, 2) ==
        100.0, a float-representation quirk) and then adding an UNROUNDED
        unlabeled figure (50.005) before a final round produced 150.0, while
        the displayed parts (100.0 label + round(50.005, 2) == 50.01
        unlabeled) sum to 150.01. incidental_total must match the latter."""
        cat = _category(db, "Vakantie kosten")
        label = IncidentalLabel(name="Vakantie")
        db.add(label)
        db.commit()
        budget = _budget(db)
        _line(db, budget, cat, 500.0)

        labeled = make_transaction(db, bedrag=-100.005, category_id=cat.id, datum=START, is_incidental=True)
        labeled.incidental_label_id = label.id
        make_transaction(db, bedrag=-50.005, category_id=cat.id, datum=START, is_incidental=True)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))

        by_label_total = sum(e.amount for e in result.summary.incidental_by_label)
        assert round(by_label_total + result.summary.unlabeled_incidental, 2) == result.summary.incidental_total
        assert result.summary.incidental_total == 150.01


class TestR2FixedGhost:
    def test_ghost_fires_only_when_closed(self, db: Session):
        cat = _category(db, "Internet", is_fixed=True)
        budget = _budget(db)
        _line(db, budget, cat, 49.99)

        closed = compute_highlights(db, budget, today=date(2026, 9, 23))
        open_ = compute_highlights(db, budget, today=date(2026, 9, 1))

        assert len(_highlights_for(closed, "fixed_ghost")) == 1
        ghost = _highlights_for(closed, "fixed_ghost")[0]
        assert ghost.severity == "warn"
        assert ghost.category_id == cat.id
        assert ghost.amount == 49.99
        assert _highlights_for(open_, "fixed_ghost") == []

    def test_no_ghost_when_paid(self, db: Session):
        cat = _category(db, "Internet", is_fixed=True)
        budget = _budget(db)
        _line(db, budget, cat, 49.99)
        make_transaction(db, bedrag=-49.99, category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        assert _highlights_for(result, "fixed_ghost") == []


class TestR3BillChange:
    def test_bill_increased_above_factor(self, db: Session):
        cat = _category(db, "Energie", is_fixed=True)
        budget = _budget(db)
        _line(db, budget, cat, 100.0)
        make_transaction(db, bedrag=-(100.0 * BILL_INCREASE_FACTOR + 1), category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "bill_change")
        assert len(cards) == 1
        assert cards[0].severity == "info"

    def test_bill_decreased_below_factor(self, db: Session):
        cat = _category(db, "Energie", is_fixed=True)
        budget = _budget(db)
        _line(db, budget, cat, 100.0)
        make_transaction(db, bedrag=-(100.0 / BILL_INCREASE_FACTOR - 1), category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "bill_change")
        assert len(cards) == 1

    def test_no_bill_change_within_factor(self, db: Session):
        cat = _category(db, "Energie", is_fixed=True)
        budget = _budget(db)
        _line(db, budget, cat, 100.0)
        make_transaction(db, bedrag=-105.0, category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        assert _highlights_for(result, "bill_change") == []

    def test_ghost_line_skipped_by_bill_change(self, db: Session):
        cat = _category(db, "Energie", is_fixed=True)
        budget = _budget(db)
        _line(db, budget, cat, 100.0)
        # no transaction: actual == 0, already covered by R2
        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        assert _highlights_for(result, "bill_change") == []
        assert len(_highlights_for(result, "fixed_ghost")) == 1


class TestR4FlexibleOverrun:
    def test_overrun_boundary_exact_threshold_does_not_fire(self, db: Session):
        cat = _category(db, "Uit eten", is_fixed=False)
        budget = _budget(db)
        plan = 200.0
        _line(db, budget, cat, plan)
        threshold = max(plan * OVERRUN_PCT, OVERRUN_MIN_EUR)
        make_transaction(db, bedrag=-(plan + threshold), category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        assert _highlights_for(result, "flexible_overrun") == []

    def test_overrun_one_cent_over_threshold_fires(self, db: Session):
        cat = _category(db, "Uit eten", is_fixed=False)
        budget = _budget(db)
        plan = 200.0
        _line(db, budget, cat, plan)
        threshold = max(plan * OVERRUN_PCT, OVERRUN_MIN_EUR)
        make_transaction(db, bedrag=-(plan + threshold + 0.01), category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "flexible_overrun")
        assert len(cards) == 1
        assert cards[0].severity == "warn"
        assert cards[0].category_id == cat.id

    def test_overrun_uses_min_eur_floor_for_small_plans(self, db: Session):
        cat = _category(db, "Snacks", is_fixed=False)
        budget = _budget(db)
        plan = 10.0  # 20% of 10 = 2, floor is 25
        _line(db, budget, cat, plan)
        make_transaction(db, bedrag=-(plan + OVERRUN_MIN_EUR + 0.01), category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        assert len(_highlights_for(result, "flexible_overrun")) == 1

    def test_subtree_aggregation_plan_on_parent_spend_on_children(self, db: Session):
        parent = _category(db, "Vrije Tijd", is_fixed=False)
        child = _category(db, "Bioscoop", is_fixed=False, parent_id=parent.id)
        budget = _budget(db)
        plan = 100.0
        _line(db, budget, parent, plan)
        threshold = max(plan * OVERRUN_PCT, OVERRUN_MIN_EUR)
        make_transaction(db, bedrag=-(plan + threshold + 5), category_id=child.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "flexible_overrun")
        assert len(cards) == 1
        assert cards[0].category_id == parent.id

    def test_child_with_own_line_excluded_from_parent_aggregate(self, db: Session):
        parent = _category(db, "Vrije Tijd", is_fixed=False)
        child = _category(db, "Bioscoop", is_fixed=False, parent_id=parent.id)
        budget = _budget(db)
        _line(db, budget, parent, 100.0)
        _line(db, budget, child, 500.0)  # child judged separately, big plan so no overrun
        make_transaction(db, bedrag=-150.0, category_id=child.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        # Parent's aggregate actual is 0 (child excluded), so no overrun on parent.
        assert _highlights_for(result, "flexible_overrun") == []

    def test_one_off_detector_at_boundary(self, db: Session):
        cat = _category(db, "Uit eten", is_fixed=False)
        budget = _budget(db)
        plan = 100.0
        _line(db, budget, cat, plan)
        threshold = max(plan * OVERRUN_PCT, OVERRUN_MIN_EUR)
        total_actual = plan + threshold + 10
        one_off_amount = total_actual * ONE_OFF_FRACTION  # exactly at the boundary
        make_transaction(
            db, bedrag=-one_off_amount, category_id=cat.id, datum=START,
            naam="Restaurant X", merchant_name="Restaurant X",
        )
        make_transaction(db, bedrag=-(total_actual - one_off_amount), category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "flexible_overrun")
        assert len(cards) == 1
        assert "Restaurant X" in cards[0].detail

    def test_one_off_detector_below_boundary_no_mention(self, db: Session):
        cat = _category(db, "Uit eten", is_fixed=False)
        budget = _budget(db)
        plan = 100.0
        _line(db, budget, cat, plan)
        threshold = max(plan * OVERRUN_PCT, OVERRUN_MIN_EUR)
        total_actual = plan + threshold + 10
        one_off_amount = total_actual * ONE_OFF_FRACTION - 1
        make_transaction(
            db, bedrag=-one_off_amount, category_id=cat.id, datum=START,
            naam="Restaurant X", merchant_name="Restaurant X",
        )
        make_transaction(db, bedrag=-(total_actual - one_off_amount), category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "flexible_overrun")
        assert len(cards) == 1
        assert "Restaurant X" not in cards[0].detail

    def test_one_off_detector_one_cent_under_boundary_no_mention(self, db: Session):
        cat = _category(db, "Uit eten", is_fixed=False)
        budget = _budget(db)
        plan = 100.0
        _line(db, budget, cat, plan)
        threshold = max(plan * OVERRUN_PCT, OVERRUN_MIN_EUR)
        total_actual = plan + threshold + 10
        one_off_amount = total_actual * ONE_OFF_FRACTION - 0.01
        make_transaction(
            db, bedrag=-one_off_amount, category_id=cat.id, datum=START,
            naam="Restaurant X", merchant_name="Restaurant X",
        )
        make_transaction(db, bedrag=-(total_actual - one_off_amount), category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "flexible_overrun")
        assert len(cards) == 1
        assert "Restaurant X" not in cards[0].detail

    def test_one_off_detector_attributes_split_receipt_by_line_item(self, db: Session):
        """Regression: the one-off detector must attribute a receipted,
        split transaction the same way compute_budget_actuals does (per
        line item category/amount), not by Transaction.category_id and the
        whole bedrag. Transaction.category_id only ever syncs from the
        'remaining' line item, so a naive whole-bedrag check keyed off it
        would miss (or misattribute) a dominant purchase living in a
        different line item's category."""
        cat = _category(db, "Uit eten", is_fixed=False)
        other_cat = _category(db, "Boodschappen", is_fixed=False)
        budget = _budget(db)
        plan = 10.0
        _line(db, budget, cat, plan)

        # tx.category_id points at the OTHER category (as it would if that
        # were the "remaining" line item's category), while the dominant
        # 80 EUR line item is categorized to `cat`.
        tx = make_transaction(
            db, bedrag=-100.0, category_id=other_cat.id, datum=START,
            naam="Restaurant X", merchant_name="Restaurant X",
        )
        receipt = Receipt(transaction_id=tx.id, total_amount=100.0)
        db.add(receipt)
        db.flush()
        db.add(LineItem(
            receipt_id=receipt.id, description="Dinner", amount=80.0, quantity=1,
            category_id=cat.id, sort_order=0,
        ))
        db.add(LineItem(
            receipt_id=receipt.id, description="Groceries", amount=20.0, quantity=1,
            category_id=other_cat.id, sort_order=1,
        ))
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "flexible_overrun")
        assert len(cards) == 1
        assert cards[0].category_id == cat.id
        # Effective actual on `cat` is 80 (the line item), not 100.
        assert cards[0].amount == 70.0
        assert "Restaurant X" in cards[0].detail
        assert "EUR 80.00" in cards[0].detail

    def test_one_off_detector_with_subtree_aggregation(self, db: Session):
        """Plan on the parent, spend on a child, one dominant purchase in
        that child: the one-off detector must search across the folded
        descendant set, not just the parent category itself."""
        parent = _category(db, "Vrije Tijd", is_fixed=False)
        child = _category(db, "Bioscoop", is_fixed=False, parent_id=parent.id)
        budget = _budget(db)
        plan = 20.0
        _line(db, budget, parent, plan)
        make_transaction(
            db, bedrag=-90.0, category_id=child.id, datum=START,
            naam="Cinema City", merchant_name="Cinema City",
        )
        make_transaction(db, bedrag=-10.0, category_id=child.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "flexible_overrun")
        assert len(cards) == 1
        assert cards[0].category_id == parent.id
        assert "Cinema City" in cards[0].detail


class TestR5Underrun:
    def test_underrun_fires_below_fraction(self, db: Session):
        cat = _category(db, "Kleding", is_fixed=False)
        budget = _budget(db)
        _line(db, budget, cat, 100.0)
        make_transaction(db, bedrag=-(100.0 * UNDERRUN_FRACTION - 1), category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "flexible_underrun")
        assert len(cards) == 1
        assert cards[0].severity == "info"

    def test_underrun_at_exact_fraction_does_not_fire(self, db: Session):
        cat = _category(db, "Kleding", is_fixed=False)
        budget = _budget(db)
        _line(db, budget, cat, 100.0)
        make_transaction(db, bedrag=-(100.0 * UNDERRUN_FRACTION), category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        assert _highlights_for(result, "flexible_underrun") == []

    def test_at_most_one_underrun_card_picks_largest_unspent(self, db: Session):
        cat_a = _category(db, "Kleding", is_fixed=False)
        cat_b = _category(db, "Hobby", is_fixed=False)
        budget = _budget(db)
        _line(db, budget, cat_a, 100.0)
        _line(db, budget, cat_b, 300.0)
        make_transaction(db, bedrag=-10.0, category_id=cat_a.id, datum=START)  # unspent 90
        make_transaction(db, bedrag=-10.0, category_id=cat_b.id, datum=START)  # unspent 290
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "flexible_underrun")
        assert len(cards) == 1
        assert cards[0].category_id == cat_b.id


class TestR6SavingsExecution:
    def test_fully_funded_pot_suppressed_when_not_all_funded(self, db: Session):
        pot_a = _category(db, "Vakantie", category_type="savings")
        pot_b = _category(db, "Auto", category_type="savings")
        budget = _budget(db)
        _line(db, budget, pot_a, 100.0)
        _line(db, budget, pot_b, 100.0)
        tx_a = make_transaction(db, bedrag=-100.0, category_id=pot_a.id, datum=START)
        tx_a.is_internal_transfer = True
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        assert _highlights_for(result, "savings_funded") == []
        assert _highlights_for(result, "savings_no_transfer") != []

    def test_aggregate_good_card_when_all_pots_funded(self, db: Session):
        pot_a = _category(db, "Vakantie", category_type="savings")
        pot_b = _category(db, "Auto", category_type="savings")
        budget = _budget(db)
        _line(db, budget, pot_a, 100.0)
        _line(db, budget, pot_b, 50.0)
        tx_a = make_transaction(db, bedrag=-100.0, category_id=pot_a.id, datum=START)
        tx_a.is_internal_transfer = True
        tx_b = make_transaction(db, bedrag=-60.0, category_id=pot_b.id, datum=START)
        tx_b.is_internal_transfer = True
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "savings_funded")
        assert len(cards) == 1
        assert cards[0].severity == "good"
        assert result.summary.pots_executed == 2
        assert result.summary.pots_planned == 2

    def test_zero_contribution_closed_is_warn(self, db: Session):
        pot = _category(db, "Vakantie", category_type="savings")
        budget = _budget(db)
        _line(db, budget, pot, 100.0)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "savings_no_transfer")
        assert len(cards) == 1
        assert cards[0].severity == "warn"

    def test_zero_contribution_open_is_info(self, db: Session):
        pot = _category(db, "Vakantie", category_type="savings")
        budget = _budget(db)
        _line(db, budget, pot, 100.0)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 1))
        cards = _highlights_for(result, "savings_no_transfer")
        assert len(cards) == 1
        assert cards[0].severity == "info"

    def test_net_withdrawal_is_warn_and_lists_transactions(self, db: Session):
        pot = _category(db, "Vakantie", category_type="savings")
        budget = _budget(db)
        _line(db, budget, pot, 100.0)
        withdrawal = make_transaction(
            db, bedrag=50.0, category_id=pot.id, datum=START, naam="Jan Janssen",
        )
        withdrawal.is_internal_transfer = True
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "savings_withdrawal")
        assert len(cards) == 1
        assert cards[0].severity == "warn"
        assert "Jan Janssen" in cards[0].detail

    def test_withdrawal_lists_up_to_three_transactions(self, db: Session):
        pot = _category(db, "Vakantie", category_type="savings")
        budget = _budget(db)
        _line(db, budget, pot, 100.0)
        for i, amount in enumerate([80.0, 60.0, 40.0, 20.0]):
            tx = make_transaction(
                db, bedrag=amount, category_id=pot.id, datum=START, naam=f"Counterparty {i}",
                volgnummer=str(i),
            )
            tx.is_internal_transfer = True
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "savings_withdrawal")
        assert len(cards) == 1
        assert cards[0].detail.count("Counterparty") == 3
        assert "Counterparty 0" in cards[0].detail
        assert "Counterparty 3" not in cards[0].detail

    def test_partial_funding_is_info(self, db: Session):
        pot = _category(db, "Vakantie", category_type="savings")
        budget = _budget(db)
        _line(db, budget, pot, 100.0)
        tx = make_transaction(db, bedrag=-40.0, category_id=pot.id, datum=START)
        tx.is_internal_transfer = True
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "savings_partial")
        assert len(cards) == 1
        assert cards[0].severity == "info"


class TestR7IncomeChange:
    def test_income_up_is_good(self, db: Session):
        cat = _category(db, "Salaris", category_type="income")
        budget = _budget(db)
        plan = 3000.0
        _line(db, budget, cat, plan)
        make_transaction(db, bedrag=plan * (1 + SALARY_CHANGE_PCT + 0.01), category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "income_change")
        assert len(cards) == 1
        assert cards[0].severity == "good"

    def test_income_down_is_info(self, db: Session):
        cat = _category(db, "Salaris", category_type="income")
        budget = _budget(db)
        plan = 3000.0
        _line(db, budget, cat, plan)
        make_transaction(db, bedrag=plan * (1 - SALARY_CHANGE_PCT - 0.01), category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "income_change")
        assert len(cards) == 1
        assert cards[0].severity == "info"

    def test_income_within_threshold_does_not_fire(self, db: Session):
        cat = _category(db, "Salaris", category_type="income")
        budget = _budget(db)
        plan = 3000.0
        _line(db, budget, cat, plan)
        make_transaction(db, bedrag=plan, category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        assert _highlights_for(result, "income_change") == []

    def test_income_change_exact_threshold_does_not_fire(self, db: Session):
        cat = _category(db, "Salaris", category_type="income")
        budget = _budget(db)
        plan = 3000.0
        _line(db, budget, cat, plan)
        make_transaction(db, bedrag=plan * (1 + SALARY_CHANGE_PCT), category_id=cat.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        assert _highlights_for(result, "income_change") == []

    def test_income_change_one_cent_over_threshold_fires(self, db: Session):
        cat = _category(db, "Salaris", category_type="income")
        budget = _budget(db)
        plan = 3000.0
        _line(db, budget, cat, plan)
        make_transaction(
            db, bedrag=plan * (1 + SALARY_CHANGE_PCT) + 0.01, category_id=cat.id, datum=START,
        )
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "income_change")
        assert len(cards) == 1
        assert cards[0].severity == "good"

    def test_multiple_income_lines_each_evaluated(self, db: Session):
        salary = _category(db, "Salaris", category_type="income")
        freelance = _category(db, "Freelance", category_type="income")
        budget = _budget(db)
        _line(db, budget, salary, 3000.0)
        _line(db, budget, freelance, 500.0)
        make_transaction(db, bedrag=3000.0 * 1.05, category_id=salary.id, datum=START)
        make_transaction(db, bedrag=500.0 * 0.5, category_id=freelance.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "income_change")
        assert len(cards) == 2


class TestR8TopExpenses:
    def test_top_three_ordering_and_tie_break(self, db: Session):
        cat = _category(db, "Boodschappen", is_fixed=False)
        budget = _budget(db)
        _line(db, budget, cat, 300.0)
        make_transaction(db, bedrag=-50.0, category_id=cat.id, datum=START, naam="A", volgnummer="1")
        make_transaction(db, bedrag=-50.0, category_id=cat.id, datum=START, naam="B", volgnummer="2")
        make_transaction(db, bedrag=-30.0, category_id=cat.id, datum=START, naam="C", volgnummer="3")
        make_transaction(db, bedrag=-10.0, category_id=cat.id, datum=START, naam="D", volgnummer="4")
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "top_expenses")
        assert len(cards) == 1
        # Two tied at 50 (A before B by id/datum tie-break), then C at 30.
        assert cards[0].detail.index("A") < cards[0].detail.index("B") < cards[0].detail.index("C")
        assert "D" not in cards[0].detail

    def test_excludes_incidental_and_internal_transfer(self, db: Session):
        cat = _category(db, "Boodschappen", is_fixed=False)
        budget = _budget(db)
        _line(db, budget, cat, 300.0)
        make_transaction(db, bedrag=-500.0, category_id=cat.id, datum=START, naam="Incidental", is_incidental=True)
        transfer = make_transaction(db, bedrag=-500.0, category_id=cat.id, datum=START, naam="Transfer")
        transfer.is_internal_transfer = True
        make_transaction(db, bedrag=-20.0, category_id=cat.id, datum=START, naam="Normal")
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "top_expenses")
        assert len(cards) == 1
        assert "Incidental" not in cards[0].detail
        assert "Transfer" not in cards[0].detail
        assert "Normal" in cards[0].detail

    def test_fires_on_open_period_too(self, db: Session):
        cat = _category(db, "Boodschappen", is_fixed=False)
        budget = _budget(db)
        _line(db, budget, cat, 300.0)
        make_transaction(db, bedrag=-20.0, category_id=cat.id, datum=START, naam="Normal")
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 1))
        assert len(_highlights_for(result, "top_expenses")) == 1


class TestR9Scorecard:
    def test_counts_consistent_with_fired_r4(self, db: Session):
        overrun_cat = _category(db, "Uit eten", is_fixed=False)
        ok_cat = _category(db, "Kleding", is_fixed=False)
        pot = _category(db, "Vakantie", category_type="savings")
        budget = _budget(db)
        _line(db, budget, overrun_cat, 100.0)
        _line(db, budget, ok_cat, 100.0)
        _line(db, budget, pot, 50.0)
        threshold = max(100.0 * OVERRUN_PCT, OVERRUN_MIN_EUR)
        make_transaction(db, bedrag=-(100.0 + threshold + 1), category_id=overrun_cat.id, datum=START)
        make_transaction(db, bedrag=-50.0, category_id=ok_cat.id, datum=START)
        tx = make_transaction(db, bedrag=-50.0, category_id=pot.id, datum=START)
        tx.is_internal_transfer = True
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        cards = _highlights_for(result, "scorecard")
        assert len(cards) == 1
        assert result.summary.flexible_total == 2
        assert result.summary.flexible_within_plan == 1
        assert result.summary.pots_planned == 1
        assert result.summary.pots_executed == 1

    def test_scorecard_closed_only(self, db: Session):
        cat = _category(db, "Kleding", is_fixed=False)
        budget = _budget(db)
        _line(db, budget, cat, 100.0)
        result = compute_highlights(db, budget, today=date(2026, 9, 1))
        assert _highlights_for(result, "scorecard") == []


class TestOrderingAndCatalog:
    def test_open_period_reduced_catalog(self, db: Session):
        fixed_cat = _category(db, "Internet", is_fixed=True)
        flexible_cat = _category(db, "Kleding", is_fixed=False)
        budget = _budget(db)
        _line(db, budget, fixed_cat, 50.0)
        _line(db, budget, flexible_cat, 100.0)
        make_transaction(db, bedrag=-500.0, category_id=flexible_cat.id, datum=START)

        result = compute_highlights(db, budget, today=date(2026, 9, 1))
        assert result.closed is False
        rules_fired = {h.rule for h in result.highlights}
        assert "fixed_ghost" not in rules_fired
        assert "flexible_overrun" not in rules_fired
        assert "scorecard" not in rules_fired

    def test_closed_flag_boundary(self, db: Session):
        budget = _budget(db)
        assert compute_highlights(db, budget, today=END).closed is True
        assert compute_highlights(db, budget, today=END - timedelta(days=1)).closed is False

    def test_full_list_ordering_catalog_then_amount_then_category_id(self, db: Session):
        cat_a = _category(db, "Uit eten", is_fixed=False)
        cat_b = _category(db, "Hobby", is_fixed=False)
        budget = _budget(db)
        _line(db, budget, cat_a, 100.0)
        _line(db, budget, cat_b, 100.0)
        threshold = max(100.0 * OVERRUN_PCT, OVERRUN_MIN_EUR)
        make_transaction(db, bedrag=-(100.0 + threshold + 50), category_id=cat_a.id, datum=START)
        make_transaction(db, bedrag=-(100.0 + threshold + 10), category_id=cat_b.id, datum=START)
        db.commit()

        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        overrun_cards = _highlights_for(result, "flexible_overrun")
        assert len(overrun_cards) == 2
        # Descending |amount|: cat_a's overrun (60) before cat_b's (20).
        assert overrun_cards[0].category_id == cat_a.id
        assert overrun_cards[1].category_id == cat_b.id
        # Rule catalog order: fixed_ghost/bill_change/flexible_overrun come
        # before scorecard in the full list.
        rule_order = [h.rule for h in result.highlights]
        assert rule_order.index("flexible_overrun") < rule_order.index("scorecard")


class TestRounding:
    def test_amounts_rounded_to_cents(self, db: Session):
        cat = _category(db, "Internet", is_fixed=True)
        budget = _budget(db)
        _line(db, budget, cat, 49.999)
        result = compute_highlights(db, budget, today=date(2026, 9, 23))
        ghost = _highlights_for(result, "fixed_ghost")[0]
        assert ghost.amount == round(49.999, 2)
