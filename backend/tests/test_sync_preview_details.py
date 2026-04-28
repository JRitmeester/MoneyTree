from datetime import date

from app.services.sync_export import build_export
from app.services.sync_import import preview_import
from app.sync_schemas import (
    ExportFile, ExportTransaction, PREVIEW_SAMPLE_LIMIT,
)
from datetime import datetime, timezone

from tests.conftest import make_category, make_transaction


def test_preview_lists_added_categories_by_name(db):
    cat = make_category(db, name="Local-Existing")
    db.commit()
    export = build_export(db, since=None)
    # Add a category to the export that isn't on destination
    from app.sync_schemas import ExportCategory
    export.categories.append(ExportCategory(name="Travel", parent_name=None, is_fixed=False, category_type="expense"))

    # Use a fresh in-memory db to play "destination"
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.models import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    dest = sessionmaker(bind=engine)()

    preview = preview_import(dest, export)
    assert "Local-Existing" in preview.add_categories
    assert "Travel" in preview.add_categories


def test_preview_lists_skipped_transactions(db):
    cat = make_category(db, name="Groceries")
    tx = make_transaction(db, category_id=cat.id, naam="Albert Heijn")
    db.commit()
    export = build_export(db, since=None)

    preview = preview_import(db, export)
    assert preview.will_skip_transactions == 1
    assert len(preview.skip_transactions) == 1
    assert preview.skip_transactions[0].import_hash == tx.import_hash


def test_preview_detects_transaction_recategorization(db):
    cat_a = make_category(db, name="OldCat")
    cat_b = make_category(db, name="NewCat")
    tx = make_transaction(db, category_id=cat_a.id, merchant_name="OldMerchant")
    db.commit()
    export = build_export(db, since=None)
    et = next(e for e in export.transactions if e.import_hash == tx.import_hash)
    et.category_name = "NewCat"
    et.merchant_name = "NewMerchant"

    preview = preview_import(db, export)
    assert preview.will_update_transactions == 1
    upd = preview.update_transactions[0]
    assert upd.old_category_name == "OldCat"
    assert upd.new_category_name == "NewCat"
    assert upd.old_merchant_name == "OldMerchant"
    assert upd.new_merchant_name == "NewMerchant"


def test_preview_truncates_long_transaction_lists(db):
    cat = make_category(db, name="Groceries")
    # Create more transactions than PREVIEW_SAMPLE_LIMIT
    for i in range(PREVIEW_SAMPLE_LIMIT + 5):
        make_transaction(db, category_id=cat.id, omschrijving=f"tx-{i}")
    db.commit()
    export = build_export(db, since=None)

    preview = preview_import(db, export)
    assert preview.will_skip_transactions == PREVIEW_SAMPLE_LIMIT + 5
    assert len(preview.skip_transactions) == PREVIEW_SAMPLE_LIMIT
