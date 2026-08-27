"""Task 2: format v3 (path-keyed) sync export/import."""
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Category
from app.services.sync_export import build_export
from app.services.sync_import import commit_import
from app.sync_schemas import ExportCategory, ExportFile
from tests.conftest import make_category, make_transaction


def _fresh_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_build_export_writes_format_version_3(db):
    export = build_export(db, since=None)
    assert export.format_version == 3


def test_export_categories_include_path(db):
    parent = make_category(db, name="Vervoer")
    child = Category(name="Auto", parent_id=parent.id)
    db.add(child)
    db.commit()

    export = build_export(db, since=None)
    auto = next(c for c in export.categories if c.name == "Auto")
    assert auto.path == "Vervoer > Auto"


def test_v3_roundtrip_two_overig_categories_under_different_parents(db):
    """The whole point of format v3: two categories named 'Overig' under
    different parents must round-trip without collapsing into one."""
    living = make_category(db, name="Living")
    travel = make_category(db, name="Travel")
    living_overig = Category(name="Overig", parent_id=living.id)
    travel_overig = Category(name="Overig", parent_id=travel.id)
    db.add_all([living_overig, travel_overig])
    db.commit()

    tx_living = make_transaction(db, category_id=living_overig.id)
    tx_travel = make_transaction(db, category_id=travel_overig.id)
    db.commit()

    export = build_export(db, since=None)
    assert export.format_version == 3

    dest = _fresh_session()
    commit_import(dest, export, update_duplicates=False)

    overigs = dest.execute(select(Category).where(Category.name == "Overig")).scalars().all()
    assert len(overigs) == 2
    parent_names = {dest.get(Category, o.parent_id).name for o in overigs}
    assert parent_names == {"Living", "Travel"}

    from app.models import Transaction
    dest_tx_living = dest.execute(
        select(Transaction).where(Transaction.import_hash == tx_living.import_hash)
    ).scalar_one()
    dest_tx_travel = dest.execute(
        select(Transaction).where(Transaction.import_hash == tx_travel.import_hash)
    ).scalar_one()
    living_overig_dest = next(o for o in overigs if dest.get(Category, o.parent_id).name == "Living")
    travel_overig_dest = next(o for o in overigs if dest.get(Category, o.parent_id).name == "Travel")
    assert dest_tx_living.category_id == living_overig_dest.id
    assert dest_tx_travel.category_id == travel_overig_dest.id


def test_v3_import_creates_missing_ancestors(db):
    """A path referencing categories not present in export.categories still
    resolves, creating missing ancestors with sensible defaults."""
    export = ExportFile(
        format_version=3,
        exported_at=datetime.now(timezone.utc),
        since=None,
        categories=[
            ExportCategory(
                name="Onderhoud", parent_name="Auto", path="Vervoer > Auto > Onderhoud",
                is_fixed=True, category_type="expense",
            ),
        ],
        category_mappings=[], budgets=[], budget_lines=[], budget_templates=[],
        transactions=[], transaction_offsets=[],
    )

    dest = _fresh_session()
    commit_import(dest, export, update_duplicates=False)

    cats = {c.name: c for c in dest.execute(select(Category)).scalars().all()}
    assert set(cats) == {"Vervoer", "Auto", "Onderhoud"}
    assert cats["Vervoer"].parent_id is None
    assert cats["Auto"].parent_id == cats["Vervoer"].id
    assert cats["Onderhoud"].parent_id == cats["Auto"].id
    # Ancestors get sensible defaults, leaf keeps its exported attributes
    assert cats["Vervoer"].category_type == "expense"
    assert cats["Vervoer"].is_fixed is False
    assert cats["Onderhoud"].is_fixed is True


def test_v2_legacy_import_still_resolves_by_bare_name(db):
    """A v2 export (pre-path, globally-unique names) still imports by name."""
    export = ExportFile(
        format_version=2,
        exported_at=datetime.now(timezone.utc),
        since=None,
        categories=[
            ExportCategory(name="Living", parent_name=None, is_fixed=False, category_type="expense"),
            ExportCategory(name="Groceries", parent_name="Living", is_fixed=False, category_type="expense"),
        ],
        category_mappings=[], budgets=[], budget_lines=[], budget_templates=[],
        transactions=[], transaction_offsets=[],
    )

    dest = _fresh_session()
    commit_import(dest, export, update_duplicates=False)

    cats = {c.name: c for c in dest.execute(select(Category)).scalars().all()}
    assert set(cats) == {"Living", "Groceries"}
    assert cats["Groceries"].parent_id == cats["Living"].id


def test_v3_budget_line_and_mapping_references_resolve_by_path(db):
    from datetime import date
    living = make_category(db, name="Living")
    living_overig = Category(name="Overig", parent_id=living.id)
    travel = make_category(db, name="Travel")
    travel_overig = Category(name="Overig", parent_id=travel.id)
    db.add_all([living_overig, travel_overig])
    db.commit()

    from app.models import Budget, BudgetLine, CategoryMapping
    budget = Budget(start_date=date(2026, 5, 1), end_date=date(2026, 5, 31))
    db.add(budget)
    db.flush()
    db.add(BudgetLine(budget_id=budget.id, category_id=travel_overig.id, amount=75.0))
    db.add(CategoryMapping(bank_category="REISKOSTEN", category_id=travel_overig.id))
    db.commit()

    export = build_export(db, since=None)
    line = next(l for l in export.budget_lines)
    mapping = next(m for m in export.category_mappings)
    assert line.category_name == "Travel > Overig"
    assert mapping.category_name == "Travel > Overig"

    dest = _fresh_session()
    commit_import(dest, export, update_duplicates=False)

    from app.models import BudgetLine as DestBudgetLine, CategoryMapping as DestMapping
    dest_line = dest.execute(select(DestBudgetLine)).scalars().one()
    dest_travel_overig = dest.execute(
        select(Category).where(Category.name == "Overig", Category.parent_id.in_(
            select(Category.id).where(Category.name == "Travel")
        ))
    ).scalar_one()
    assert dest_line.category_id == dest_travel_overig.id
    dest_mapping = dest.execute(select(DestMapping)).scalars().one()
    assert dest_mapping.category_id == dest_travel_overig.id
