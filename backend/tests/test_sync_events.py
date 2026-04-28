from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    Base, Budget, BudgetLine, BudgetTemplate, Category, CategoryMapping,
    SyncEvent, Transaction,
)
from app.services.sync_events import (
    EVENT_BUDGET_DELETE, EVENT_CATEGORY_DELETE, EVENT_CATEGORY_MAPPING_DELETE,
    EVENT_CATEGORY_RENAME, EVENT_CATEGORY_UPDATE, record_event,
)
from app.services.sync_export import build_export
from app.services.sync_import import commit_import, preview_import
from tests.conftest import make_category, make_transaction


def _fresh():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_record_event_appends_uuid_and_payload(db):
    record_event(db, EVENT_CATEGORY_RENAME, {"old_name": "A", "new_name": "B"})
    db.commit()
    rows = db.execute(select(SyncEvent)).scalars().all()
    assert len(rows) == 1
    assert rows[0].event_type == EVENT_CATEGORY_RENAME
    assert len(rows[0].event_id) == 36  # uuid4 string
    import json
    assert json.loads(rows[0].payload_json) == {"old_name": "A", "new_name": "B"}


def test_export_includes_sync_events(db):
    make_category(db, name="Groceries")
    record_event(db, EVENT_CATEGORY_RENAME, {"old_name": "Boodschappen", "new_name": "Groceries"})
    db.commit()

    export = build_export(db, since=None)
    assert len(export.sync_events) == 1
    assert export.sync_events[0].event_type == EVENT_CATEGORY_RENAME


def test_category_rename_event_applies_on_import(db):
    # Source: rename "OldName" → "NewName"
    cat = make_category(db, name="OldName")
    record_event(db, EVENT_CATEGORY_RENAME, {"old_name": "OldName", "new_name": "NewName"})
    cat.name = "NewName"
    db.commit()
    export = build_export(db, since=None)

    # Destination: still has "OldName"
    dest = _fresh()
    dest.add(Category(name="OldName"))
    dest.commit()

    commit_import(dest, export, update_duplicates=False)
    cats = {c.name for c in dest.execute(select(Category)).scalars().all()}
    assert "NewName" in cats
    assert "OldName" not in cats


def test_category_delete_event_applies_on_import(db):
    cat = make_category(db, name="ToDelete")
    record_event(db, EVENT_CATEGORY_DELETE, {"name": "ToDelete"})
    db.delete(cat)
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    dest_cat = Category(name="ToDelete")
    dest.add(dest_cat)
    dest.commit()

    commit_import(dest, export, update_duplicates=False)
    cats = dest.execute(select(Category)).scalars().all()
    assert all(c.name != "ToDelete" for c in cats)


def test_category_delete_event_nullifies_transaction_refs(db):
    cat = make_category(db, name="ToDelete")
    record_event(db, EVENT_CATEGORY_DELETE, {"name": "ToDelete"})
    db.delete(cat)
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    dest_cat = Category(name="ToDelete")
    dest.add(dest_cat)
    dest.flush()
    dest_tx = Transaction(
        datum=date(2026, 4, 1), rekening="NL00", valuta_saldo="EUR", saldo_voor_boeking=0.0,
        valuta="EUR", bedrag=-10.0, verwerkingsdatum=date(2026, 4, 1), valutadatum=date(2026, 4, 1),
        code="GT", type="BET", volgnummer="1", omschrijving="x", afschriftnummer="1", categorie="x",
        import_hash="hash-x", category_id=dest_cat.id,
    )
    dest.add(dest_tx)
    dest.commit()

    commit_import(dest, export, update_duplicates=False)
    refreshed = dest.execute(select(Transaction).where(Transaction.import_hash == "hash-x")).scalar_one()
    assert refreshed.category_id is None


def test_sync_events_are_idempotent(db):
    make_category(db, name="Stable")
    record_event(db, EVENT_CATEGORY_RENAME, {"old_name": "Boodschappen", "new_name": "Stable"})
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    dest.add(Category(name="Boodschappen"))
    dest.commit()

    commit_import(dest, export, update_duplicates=False)
    commit_import(dest, export, update_duplicates=False)

    cats = {c.name for c in dest.execute(select(Category)).scalars().all()}
    assert "Stable" in cats
    assert "Boodschappen" not in cats
    # Only one SyncEvent row recorded on dest (no duplicates)
    rows = dest.execute(select(SyncEvent)).scalars().all()
    assert len(rows) == 1


def test_preview_counts_apply_vs_skip_sync_events(db):
    make_category(db, name="Stable")
    record_event(db, EVENT_CATEGORY_RENAME, {"old_name": "Old", "new_name": "Stable"})
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    dest.add(Category(name="Old"))
    dest.commit()

    p1 = preview_import(dest, export)
    assert p1.will_apply_sync_events == 1
    assert p1.will_skip_sync_events == 0

    commit_import(dest, export, update_duplicates=False)
    p2 = preview_import(dest, export)
    assert p2.will_apply_sync_events == 0
    assert p2.will_skip_sync_events == 1


def test_budget_delete_event_applies_on_import(db):
    budget = Budget(start_date=date(2026, 4, 1), end_date=date(2026, 5, 1))
    db.add(budget)
    db.flush()
    record_event(db, EVENT_BUDGET_DELETE, {"start_date": "2026-04-01"})
    db.delete(budget)
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    dest.add(Budget(start_date=date(2026, 4, 1), end_date=date(2026, 5, 1)))
    dest.commit()

    commit_import(dest, export, update_duplicates=False)
    remaining = dest.execute(select(Budget)).scalars().all()
    assert all(b.start_date != date(2026, 4, 1) for b in remaining)


def test_category_mapping_delete_event_applies_on_import(db):
    cat = make_category(db, name="Cat")
    db.add(CategoryMapping(bank_category="Boodschappen", category_id=cat.id))
    db.flush()
    record_event(db, EVENT_CATEGORY_MAPPING_DELETE, {"bank_category": "Boodschappen"})
    db.execute(__import__("sqlalchemy").delete(CategoryMapping).where(
        CategoryMapping.bank_category == "Boodschappen"
    ))
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    dest_cat = Category(name="Cat")
    dest.add(dest_cat)
    dest.flush()
    dest.add(CategoryMapping(bank_category="Boodschappen", category_id=dest_cat.id))
    dest.commit()

    commit_import(dest, export, update_duplicates=False)
    mappings = dest.execute(select(CategoryMapping)).scalars().all()
    assert all(m.bank_category != "Boodschappen" for m in mappings)


def test_unknown_event_type_is_ignored(db):
    record_event(db, "future.unknown.event", {"foo": "bar"})
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    # Should not raise
    commit_import(dest, export, update_duplicates=False)
    # Event still gets recorded as applied (idempotency)
    rows = dest.execute(select(SyncEvent)).scalars().all()
    assert len(rows) == 1


def test_rename_event_no_op_when_old_name_absent_on_dest(db):
    """If dest doesn't have the old-name category, the rename is a silent no-op."""
    record_event(db, EVENT_CATEGORY_RENAME, {"old_name": "Ghost", "new_name": "Phantom"})
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    commit_import(dest, export, update_duplicates=False)
    cats = dest.execute(select(Category)).scalars().all()
    assert all(c.name != "Phantom" for c in cats)
