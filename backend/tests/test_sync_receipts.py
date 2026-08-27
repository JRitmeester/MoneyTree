import base64
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import UPLOADS_DIR
from app.models import Base, LineItem, Receipt
from app.services.sync_export import build_export
from app.services.sync_import import commit_import, preview_import
from tests.conftest import make_category, make_transaction


def _fresh():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _write_image(filename: str, data: bytes = b"FAKEIMG") -> str:
    """Write a fake image into UPLOADS_DIR and return its relative path."""
    target_dir = Path(UPLOADS_DIR) / "test"
    target_dir.mkdir(parents=True, exist_ok=True)
    full = target_dir / filename
    full.write_bytes(data)
    return str(full.relative_to(UPLOADS_DIR))


def test_export_includes_receipt_with_base64_image(db):
    cat = make_category(db, name="Groceries")
    tx = make_transaction(db, category_id=cat.id)
    relative = _write_image("test-receipt.jpg", b"PRETEND-JPEG-BYTES")
    receipt = Receipt(
        transaction_id=tx.id, date=date(2026, 4, 1), total_amount=42.5,
        merchant_name="AH", image_path=relative, ocr_raw_text="some text",
    )
    db.add(receipt); db.flush()
    db.add(LineItem(receipt_id=receipt.id, description="bread", amount=2.5, quantity=1, sort_order=0))
    db.commit()

    export = build_export(db, since=None)
    assert len(export.receipts) == 1
    er = export.receipts[0]
    assert er.transaction_import_hash == tx.import_hash
    assert er.merchant_name == "AH"
    assert er.image_filename == "test-receipt.jpg"
    assert base64.b64decode(er.image_base64) == b"PRETEND-JPEG-BYTES"
    assert len(er.line_items) == 1
    assert er.line_items[0].description == "bread"


def test_import_creates_receipt_with_image_and_line_items(db):
    cat = make_category(db, name="Groceries")
    tx = make_transaction(db, category_id=cat.id)
    relative = _write_image("import-receipt.jpg", b"IMG-BYTES-XYZ")
    receipt = Receipt(
        transaction_id=tx.id, date=date(2026, 4, 1), total_amount=42.5,
        merchant_name="AH", image_path=relative,
    )
    db.add(receipt); db.flush()
    db.add(LineItem(receipt_id=receipt.id, description="bread", amount=2.5, quantity=1, sort_order=0))
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    commit_import(dest, export, update_duplicates=False)

    receipts = dest.execute(select(Receipt)).scalars().all()
    assert len(receipts) == 1
    r = receipts[0]
    assert r.merchant_name == "AH"
    assert r.image_path is not None
    full = Path(UPLOADS_DIR) / r.image_path
    assert full.is_file()
    assert full.read_bytes() == b"IMG-BYTES-XYZ"
    line_items = dest.execute(select(LineItem)).scalars().all()
    assert len(line_items) == 1
    assert line_items[0].description == "bread"


def test_import_skips_receipt_when_destination_already_has_one(db):
    cat = make_category(db, name="Groceries")
    tx = make_transaction(db, category_id=cat.id)
    db.add(Receipt(transaction_id=tx.id, merchant_name="local-AH"))
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    # Pre-seed dest with a receipt for the same transaction
    from tests.conftest import make_category as mc, make_transaction as mt
    dest_cat = mc(dest, name="Groceries")
    dest_tx = mt(dest, category_id=dest_cat.id)
    # Use the export's own tx hash so commit_import skips by import_hash
    et = export.transactions[0]
    dest_tx.import_hash = et.import_hash
    dest.add(Receipt(transaction_id=dest_tx.id, merchant_name="dest-original"))
    dest.commit()

    commit_import(dest, export, update_duplicates=False)
    rows = dest.execute(select(Receipt)).scalars().all()
    # Only the pre-existing dest receipt (NAS-wins)
    assert len(rows) == 1
    assert rows[0].merchant_name == "dest-original"


def test_preview_counts_receipts(db):
    cat = make_category(db, name="Groceries")
    tx1 = make_transaction(db, category_id=cat.id)
    tx2 = make_transaction(db, category_id=cat.id)
    db.add(Receipt(transaction_id=tx1.id, merchant_name="A"))
    db.add(Receipt(transaction_id=tx2.id, merchant_name="B"))
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    preview = preview_import(dest, export)
    assert preview.will_add_receipts == 2
    assert preview.will_skip_receipts == 0


def test_export_includes_standalone_receipts_without_transaction(db):
    """Receipts not linked to a transaction are exported too, with a null hash."""
    db.add(Receipt(
        transaction_id=None, date=date(2026, 4, 1), total_amount=12.5,
        merchant_name="Standalone Shop", ocr_raw_text="raw text",
    ))
    db.commit()
    export = build_export(db, since=None)
    assert len(export.receipts) == 1
    er = export.receipts[0]
    assert er.transaction_import_hash is None
    assert er.merchant_name == "Standalone Shop"


def test_export_standalone_receipt_includes_image_and_line_items(db):
    relative = _write_image("standalone-receipt.jpg", b"STANDALONE-BYTES")
    receipt = Receipt(
        transaction_id=None, date=date(2026, 4, 1), total_amount=8.0,
        merchant_name="Standalone Shop", image_path=relative,
    )
    db.add(receipt); db.flush()
    db.add(LineItem(receipt_id=receipt.id, description="milk", amount=1.5, quantity=1, sort_order=0))
    db.commit()

    export = build_export(db, since=None)
    er = export.receipts[0]
    assert er.transaction_import_hash is None
    assert base64.b64decode(er.image_base64) == b"STANDALONE-BYTES"
    assert len(er.line_items) == 1
    assert er.line_items[0].description == "milk"


def test_import_creates_standalone_receipt_with_image(db):
    relative = _write_image("standalone-import.jpg", b"IMG-STANDALONE")
    receipt = Receipt(
        transaction_id=None, date=date(2026, 4, 1), total_amount=12.5,
        merchant_name="Standalone Shop", image_path=relative, ocr_raw_text="raw",
    )
    db.add(receipt); db.flush()
    db.add(LineItem(receipt_id=receipt.id, description="bread", amount=2.5, quantity=1, sort_order=0))
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    commit_import(dest, export, update_duplicates=False)

    receipts = dest.execute(select(Receipt)).scalars().all()
    assert len(receipts) == 1
    r = receipts[0]
    assert r.transaction_id is None
    assert r.merchant_name == "Standalone Shop"
    full = Path(UPLOADS_DIR) / r.image_path
    assert full.is_file()
    assert full.read_bytes() == b"IMG-STANDALONE"
    line_items = dest.execute(select(LineItem)).scalars().all()
    assert len(line_items) == 1


def test_import_standalone_receipt_twice_does_not_duplicate(db):
    """Importing the same export twice must not duplicate a standalone receipt."""
    db.add(Receipt(
        transaction_id=None, date=date(2026, 4, 1), total_amount=12.5,
        merchant_name="Standalone Shop", ocr_raw_text="raw",
    ))
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    commit_import(dest, export, update_duplicates=False)
    commit_import(dest, export, update_duplicates=False)

    receipts = dest.execute(select(Receipt)).scalars().all()
    assert len(receipts) == 1


def test_import_skips_standalone_receipt_matching_existing_on_dest(db):
    """A standalone receipt matching an existing one exactly on
    (date, total_amount, merchant_name, ocr_raw_text) is skipped as a duplicate."""
    db.add(Receipt(
        transaction_id=None, date=date(2026, 4, 1), total_amount=12.5,
        merchant_name="Standalone Shop", ocr_raw_text="raw",
    ))
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    dest.add(Receipt(
        transaction_id=None, date=date(2026, 4, 1), total_amount=12.5,
        merchant_name="Standalone Shop", ocr_raw_text="raw",
    ))
    dest.commit()

    commit_import(dest, export, update_duplicates=False)
    receipts = dest.execute(select(Receipt)).scalars().all()
    assert len(receipts) == 1


def test_preview_counts_standalone_receipts(db):
    db.add(Receipt(
        transaction_id=None, date=date(2026, 4, 1), total_amount=12.5,
        merchant_name="Standalone Shop", ocr_raw_text="raw",
    ))
    db.commit()
    export = build_export(db, since=None)

    dest = _fresh()
    preview = preview_import(dest, export)
    assert preview.will_add_receipts == 1
    assert preview.will_skip_receipts == 0
