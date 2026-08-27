"""Task 2: format v3 (path-keyed) sync export/import."""
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Category
from app.services.sync_export import build_export
from app.services.sync_import import commit_import, preview_import
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


# --- Fix review: category.update path fields, safe fallback lookups,
# --- ambiguous v1/v2 reference resolution ---


def test_category_update_event_carries_path_fields(db):
    """The router should record `path`/`parent_path` on category.update
    events alongside the legacy `parent_name` field."""
    from app.services.sync_events import EVENT_CATEGORY_UPDATE, record_event

    bills = make_category(db, name="Bills")
    utilities = Category(name="Utilities", parent_id=bills.id, is_fixed=False)
    db.add(utilities)
    db.commit()

    record_event(db, EVENT_CATEGORY_UPDATE, {
        "name": "Utilities", "parent_name": "Bills",
        "path": "Bills > Utilities", "parent_path": "Bills",
        "is_fixed": True, "category_type": "expense",
    })
    db.commit()

    export = build_export(db, since=None)
    ev = next(e for e in export.sync_events if e.event_type == "category.update")
    assert ev.payload["path"] == "Bills > Utilities"
    assert ev.payload["parent_path"] == "Bills"


def test_category_update_event_resolves_by_path_when_name_is_ambiguous(db):
    """A destination with two same-named categories under different parents
    must not have a category.update event guess between them: the path
    field disambiguates."""
    from app.services.sync_events import EVENT_CATEGORY_UPDATE, record_event

    make_category(db, name="Bills")
    record_event(db, EVENT_CATEGORY_UPDATE, {
        "name": "Utilities", "parent_name": "Bills",
        "path": "Bills > Utilities", "parent_path": "Bills",
        "is_fixed": True, "category_type": "expense",
    })
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh_session()
    dest_bills = Category(name="Bills")
    dest_other = Category(name="OtherParent")
    dest.add_all([dest_bills, dest_other])
    dest.flush()
    dest_correct = Category(name="Utilities", parent_id=dest_bills.id, is_fixed=False)
    dest_decoy = Category(name="Utilities", parent_id=dest_other.id, is_fixed=False)
    dest.add_all([dest_correct, dest_decoy])
    dest.commit()

    commit_import(dest, export, update_duplicates=False)

    dest.refresh(dest_correct)
    dest.refresh(dest_decoy)
    assert dest_correct.is_fixed is True
    assert dest_decoy.is_fixed is False


def test_rename_event_ambiguous_old_name_skips_with_soft_conflict(db):
    """A legacy (name-only) rename event whose old_name matches more than
    one category on the destination must not crash or guess: skip with a
    soft conflict."""
    from app.services.sync_events import EVENT_CATEGORY_RENAME, record_event

    record_event(db, EVENT_CATEGORY_RENAME, {"old_name": "Ghost", "new_name": "Renamed"})
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh_session()
    parent_a = Category(name="A")
    parent_b = Category(name="B")
    dest.add_all([parent_a, parent_b])
    dest.flush()
    dest.add_all([
        Category(name="Ghost", parent_id=parent_a.id),
        Category(name="Ghost", parent_id=parent_b.id),
    ])
    dest.commit()

    preview = commit_import(dest, export, update_duplicates=False)

    names = [c.name for c in dest.execute(select(Category)).scalars().all()]
    assert names.count("Ghost") == 2
    assert "Renamed" not in names
    assert any(c.code == "category_name_ambiguous" for c in preview.soft_conflicts)


def test_merge_event_ambiguous_source_name_skips_with_soft_conflict(db):
    """A legacy (name-only) merge event whose source_name matches more than
    one category on the destination must skip with a soft conflict rather
    than merging an arbitrary one away."""
    from app.services.sync_events import EVENT_CATEGORY_MERGE, record_event

    record_event(db, EVENT_CATEGORY_MERGE, {"source_name": "Dup", "target_name": "Target"})
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh_session()
    parent_a = Category(name="A")
    parent_b = Category(name="B")
    target = Category(name="Target")
    dest.add_all([parent_a, parent_b, target])
    dest.flush()
    dest.add_all([
        Category(name="Dup", parent_id=parent_a.id),
        Category(name="Dup", parent_id=parent_b.id),
    ])
    dest.commit()

    preview = commit_import(dest, export, update_duplicates=False)

    names = [c.name for c in dest.execute(select(Category)).scalars().all()]
    assert names.count("Dup") == 2
    assert any(c.code == "category_name_ambiguous" for c in preview.soft_conflicts)


def test_v2_import_ambiguous_category_name_reference_is_soft_conflict_no_mutation(db):
    """Destination already has two 'Overig' categories under different
    parents (only possible after the per-parent uniqueness migration). A
    v2 file referencing 'Overig' by bare name cannot disambiguate: it must
    be skipped with a soft conflict, never silently bound to an arbitrary
    one of the two."""
    from app.models import BudgetTemplate
    from app.sync_schemas import ExportBudgetTemplate

    parent_a = make_category(db, name="Living")
    parent_b = make_category(db, name="Travel")
    db.add_all([
        Category(name="Overig", parent_id=parent_a.id),
        Category(name="Overig", parent_id=parent_b.id),
    ])
    db.commit()

    export = ExportFile(
        format_version=2,
        exported_at=datetime.now(timezone.utc),
        since=None,
        categories=[],
        category_mappings=[], budgets=[], budget_lines=[],
        budget_templates=[ExportBudgetTemplate(category_name="Overig", amount=50.0)],
        transactions=[], transaction_offsets=[],
    )

    preview = preview_import(db, export)
    assert any(c.code == "category_name_ambiguous" for c in preview.soft_conflicts)

    commit_import(db, export, update_duplicates=False)
    templates = db.execute(select(BudgetTemplate)).scalars().all()
    assert templates == []
