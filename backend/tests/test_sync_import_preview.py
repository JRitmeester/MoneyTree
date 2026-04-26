from datetime import date, datetime, timezone

from app.services.sync_export import build_export
from app.services.sync_import import preview_import
from tests.conftest import make_category, make_transaction


def _empty_export():
    from app.sync_schemas import ExportFile
    return ExportFile(
        format_version=1, exported_at=datetime.now(timezone.utc), since=None,
        categories=[], category_mappings=[], budgets=[], budget_lines=[],
        budget_templates=[], transactions=[], transaction_offsets=[],
    )


def test_preview_additive_into_empty_db(db):
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.commit()
    export = build_export(db, since=None)

    # New empty session simulating the destination
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.models import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    dest = sessionmaker(bind=engine)()

    preview = preview_import(dest, export)
    assert preview.will_add_categories == 1
    assert preview.will_add_transactions == 1
    assert preview.hard_conflicts == []


def test_preview_dedup_existing_transactions(db):
    cat = make_category(db, name="Groceries")
    tx = make_transaction(db, category_id=cat.id)
    db.commit()
    export = build_export(db, since=None)

    preview = preview_import(db, export)
    assert preview.will_add_transactions == 0
    assert preview.will_skip_transactions == 1


def test_preview_detects_overlapping_budget_hard_conflict(db):
    from app.models import Budget
    db.add(Budget(start_date=date(2026, 4, 1), end_date=date(2026, 5, 1)))
    db.commit()

    export = _empty_export()
    from app.sync_schemas import ExportBudget
    export.budgets.append(ExportBudget(start_date=date(2026, 4, 15), end_date=date(2026, 5, 15)))

    preview = preview_import(db, export)
    assert any(c.code == "budget_overlap" and c.severity == "hard" for c in preview.hard_conflicts)


def test_preview_flags_attribute_diff_on_existing_category(db):
    make_category(db, name="Groceries")  # default category_type=expense
    db.commit()

    export = _empty_export()
    from app.sync_schemas import ExportCategory
    export.categories.append(ExportCategory(
        name="Groceries", parent_name=None, is_fixed=True, category_type="income",
    ))

    preview = preview_import(db, export)
    assert preview.will_add_categories == 0
    assert any(c.code == "category_attr_diff" and c.severity == "soft" for c in preview.soft_conflicts)
