from datetime import date, datetime, timezone

from sqlalchemy import select

from app.models import ImportedExport
from app.services.sync_export import build_export
from app.services.sync_import import commit_import, preview_import
from tests.conftest import make_category, make_transaction


def test_export_includes_unique_export_id(db):
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.commit()

    a = build_export(db, since=None)
    b = build_export(db, since=None)

    assert a.export_id is not None
    assert b.export_id is not None
    assert a.export_id != b.export_id


def test_commit_records_imported_export(db):
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.commit()
    export = build_export(db, since=None)

    commit_import(db, export, update_duplicates=False)

    rows = db.execute(select(ImportedExport)).scalars().all()
    assert len(rows) == 1
    assert rows[0].export_id == export.export_id
    assert rows[0].transactions_added == 0  # tx already existed (dedup), so zero added


def test_preview_flags_already_imported_export(db):
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.commit()
    export = build_export(db, since=None)

    commit_import(db, export, update_duplicates=False)
    preview = preview_import(db, export)

    codes = {c.code for c in preview.soft_conflicts}
    assert "export_already_imported" in codes


def test_preview_does_not_flag_first_import(db):
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.commit()
    export = build_export(db, since=None)

    preview = preview_import(db, export)

    codes = {c.code for c in preview.soft_conflicts}
    assert "export_already_imported" not in codes


def test_legacy_export_without_export_id_works(db):
    """Older exports without export_id should still import without errors."""
    cat = make_category(db, name="Groceries")
    make_transaction(db, category_id=cat.id)
    db.commit()
    export = build_export(db, since=None)
    export.export_id = None  # simulate legacy export

    preview = preview_import(db, export)
    assert preview.hard_conflicts == []

    commit_import(db, export, update_duplicates=False)
    rows = db.execute(select(ImportedExport)).scalars().all()
    assert len(rows) == 0  # no audit row written for legacy exports
