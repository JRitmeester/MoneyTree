import base64
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete as sa_delete, select, update as sa_update
from sqlalchemy.orm import Session

from ..config import UPLOADS_DIR
from ..models import (
    Budget, BudgetLine, BudgetTemplate, Category, CategoryMapping,
    AllocationBucket, ImportedExport, IncidentalLabel, LineItem, OwnAccount, Receipt, SyncEvent,
    Transaction, TransactionOffset,
)
from ..sync_schemas import (
    ExportFile, ExportReceipt, ExportSyncEvent, ImportConflict, ImportPreview,
    PREVIEW_SAMPLE_LIMIT, TransactionPreview, TransactionUpdatePreview,
)
from .category_merge import apply_category_merge
from .category_paths import (
    PATH_SEPARATOR, full_category_path, resolve_or_create_category_path, split_category_path,
)


def _category_name_counts(db: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in db.execute(select(Category.name)).scalars().all():
        counts[name] = counts.get(name, 0) + 1
    return counts


def _category_index(db: Session) -> dict[str, Category]:
    """Name-keyed index, used to resolve category references in
    format_version 1/2 files. Names were guaranteed globally unique when
    those files were written, but the destination may since have gained
    per-parent duplicates (e.g. via format_version 3 imports or direct
    creation); a name shared by more than one category on this device is
    excluded here rather than arbitrarily binding to one of them -- see
    _ambiguous_category_names / _resolve_v1v2_ref for the caller-side
    soft-conflict reporting."""
    counts = _category_name_counts(db)
    return {c.name: c for c in db.execute(select(Category)).scalars().all() if counts[c.name] == 1}


def _ambiguous_category_names(db: Session) -> set[str]:
    """Names shared by more than one category on this device -- a v1/v2
    bare-name reference to one of these cannot be resolved unambiguously."""
    return {name for name, count in _category_name_counts(db).items() if count > 1}


def _find_category_by_name_safe(
    db: Session, name: str, conflicts: list[ImportConflict], context: str,
) -> Category | None:
    """Look up a category by bare name for sync-event fallback resolution
    (v1/v2 replay data, or a v3 event missing its path fields). Never
    raises: zero matches is a normal no-op (return None, caller skips);
    more than one match -- now possible since names are only unique
    per-parent -- also skips, but records a soft conflict naming the
    ambiguous category instead of silently guessing one."""
    matches = db.execute(select(Category).where(Category.name == name)).scalars().all()
    if len(matches) > 1:
        conflicts.append(ImportConflict(
            code="category_name_ambiguous", severity="soft",
            message=f"Category name '{name}' is ambiguous on this device; {context} skipped",
        ))
        return None
    return matches[0] if matches else None


def _resolve_v1v2_ref(
    ref: str | None,
    cat_idx: dict[str, Category],
    ambiguous_names: set[str],
    conflicts: list[ImportConflict],
) -> Category | None:
    """Resolve a bare-name category reference from a v1/v2 file. `cat_idx`
    already excludes ambiguous names (see _category_index), so this mainly
    exists to record a soft conflict distinguishing "ambiguous" misses from
    genuinely-absent ones."""
    if not ref:
        return None
    if ref in ambiguous_names:
        conflicts.append(ImportConflict(
            code="category_name_ambiguous", severity="soft",
            message=f"Category name '{ref}' is ambiguous on this device; reference skipped",
        ))
        return None
    return cat_idx.get(ref)


def _category_path_index(db: Session) -> dict[str, Category]:
    """Path-keyed index, used to resolve category references in
    format_version 3 files (names unique per-parent only)."""
    cats = db.execute(select(Category)).scalars().all()
    cat_by_id = {c.id: c for c in cats}
    return {full_category_path(c.id, cat_by_id): c for c in cats}


def _lookup_category_ref(
    ref: str | None,
    format_version: int,
    ref_idx: dict[str, Category],
    db: Session,
) -> Category | None:
    """Resolve a category_name-style reference (bare name for v1/v2, path
    for v3) against `ref_idx`. v3 creates missing ancestors (and the leaf,
    if missing) with sensible defaults; v1/v2 never creates -- a miss is
    simply skipped, matching pre-v3 behavior."""
    if not ref:
        return None
    if format_version == 3:
        return resolve_or_create_category_path(db, ref, ref_idx)
    return ref_idx.get(ref)


def _budget_index(db: Session) -> dict[str, Budget]:
    return {b.start_date.isoformat(): b for b in db.execute(select(Budget)).scalars().all()}


def _tx_hashes(db: Session) -> set[str]:
    return set(db.execute(select(Transaction.import_hash)).scalars().all())


def _incidental_label_index(db: Session) -> dict[str, IncidentalLabel]:
    return {
        l.name: l
        for l in db.execute(select(IncidentalLabel)).scalars().all()
    }


def _budget_overlaps(db: Session, start, end, exclude_start=None) -> Budget | None:
    q = select(Budget).where(Budget.start_date < end, Budget.end_date > start)
    return next(
        (b for b in db.execute(q).scalars().all()
         if exclude_start is None or b.start_date != exclude_start),
        None,
    )


def preview_import(db: Session, export: ExportFile) -> ImportPreview:
    preview = ImportPreview()

    if export.export_id:
        prior = db.execute(
            select(ImportedExport).where(ImportedExport.export_id == export.export_id)
        ).scalar_one_or_none()
        if prior is not None:
            preview.soft_conflicts.append(ImportConflict(
                code="export_already_imported", severity="soft",
                message=(
                    f"This export (id {export.export_id}) was already imported on "
                    f"{prior.imported_at.isoformat()}. Re-importing is safe (idempotent), "
                    "but you may be looking for a newer export."
                ),
            ))

    is_v3 = export.format_version == 3
    cat_idx = _category_index(db)
    ambiguous_names = set() if is_v3 else _ambiguous_category_names(db)
    ref_idx = _category_path_index(db) if is_v3 else cat_idx
    for ec in export.categories:
        effective_path = ec.path or ec.name
        existing = ref_idx.get(effective_path) if is_v3 else cat_idx.get(ec.name)
        if existing is None:
            preview.will_add_categories += 1
            if len(preview.add_categories) < PREVIEW_SAMPLE_LIMIT:
                preview.add_categories.append(ec.name)
        else:
            if is_v3:
                # Existing was matched by exact path, so its parent chain
                # already matches ec's implied hierarchy by construction.
                attr_diff = (
                    existing.is_fixed != ec.is_fixed
                    or existing.category_type != ec.category_type
                )
            else:
                attr_diff = (
                    existing.is_fixed != ec.is_fixed
                    or existing.category_type != ec.category_type
                    or (existing.parent.name if existing.parent else None) != ec.parent_name
                )
            if attr_diff:
                preview.soft_conflicts.append(ImportConflict(
                    code="category_attr_diff", severity="soft",
                    message=f"Category '{ec.name}' exists on destination with different attributes; NAS values kept.",
                ))

    if not is_v3:
        # Validate parent_name resolves. v3 never hard-conflicts here: a
        # missing ancestor is simply created (see resolve_or_create_category_path).
        export_names = {c.name for c in export.categories}
        for ec in export.categories:
            if ec.parent_name and ec.parent_name not in export_names and ec.parent_name not in cat_idx:
                preview.hard_conflicts.append(ImportConflict(
                    code="parent_name_unresolved", severity="hard",
                    message=f"Category '{ec.name}' has parent_name '{ec.parent_name}' that does not exist on destination or in export.",
                ))

    mapping_keys = {m.bank_category for m in db.execute(select(CategoryMapping)).scalars().all()}
    for em in export.category_mappings:
        if em.bank_category not in mapping_keys:
            preview.will_add_category_mappings += 1
        else:
            preview.soft_conflicts.append(ImportConflict(
                code="mapping_conflict", severity="soft",
                message=f"CategoryMapping for '{em.bank_category}' exists; NAS mapping kept.",
            ))

    bud_idx = _budget_index(db)
    export_budget_starts = {b.start_date for b in export.budgets}
    for eb in export.budgets:
        if eb.start_date.isoformat() not in bud_idx:
            overlap = _budget_overlaps(db, eb.start_date, eb.end_date, exclude_start=eb.start_date)
            if overlap is not None:
                preview.hard_conflicts.append(ImportConflict(
                    code="budget_overlap", severity="hard",
                    message=f"Imported budget {eb.start_date}–{eb.end_date} overlaps existing budget {overlap.start_date}–{overlap.end_date}.",
                ))
            else:
                preview.will_add_budgets += 1

    line_keys = {(l.budget_id, l.category_id) for l in db.execute(select(BudgetLine)).scalars().all()}
    for el in export.budget_lines:
        budget = bud_idx.get(el.budget_start_date.isoformat())
        if is_v3:
            category = ref_idx.get(el.category_name)
        else:
            category = _resolve_v1v2_ref(el.category_name, cat_idx, ambiguous_names, preview.soft_conflicts)
        if budget is None or category is None:
            preview.will_add_budget_lines += 1
            continue
        if (budget.id, category.id) in line_keys:
            preview.will_update_budget_lines += 1
        else:
            preview.will_add_budget_lines += 1

    tmpl_cat_ids = {t.category_id for t in db.execute(select(BudgetTemplate)).scalars().all()}
    for et in export.budget_templates:
        if is_v3:
            cat = ref_idx.get(et.category_name)
        else:
            cat = _resolve_v1v2_ref(et.category_name, cat_idx, ambiguous_names, preview.soft_conflicts)
        if cat is None or cat.id not in tmpl_cat_ids:
            preview.will_add_budget_templates += 1
        else:
            preview.soft_conflicts.append(ImportConflict(
                code="template_conflict", severity="soft",
                message=f"BudgetTemplate for '{et.category_name}' exists; NAS amount kept.",
            ))

    label_idx = _incidental_label_index(db)
    label_name_by_id = {l.id: l.name for l in label_idx.values()}
    for name in export.incidental_labels:
        if name not in label_idx:
            preview.will_add_incidental_labels += 1

    existing_account_ibans = {
        a.iban for a in db.execute(select(OwnAccount)).scalars().all()
    }
    for ea in export.own_accounts:
        if ea.iban not in existing_account_ibans:
            preview.will_add_own_accounts += 1
        else:
            preview.soft_conflicts.append(ImportConflict(
                code="own_account_conflict", severity="soft",
                message=f"Own account with IBAN '{ea.iban}' exists; destination values kept.",
            ))

    existing_bucket_names = {
        b.name for b in db.execute(select(AllocationBucket)).scalars().all()
    }
    for eb in export.allocation_buckets:
        if eb.name not in existing_bucket_names:
            preview.will_add_allocation_buckets += 1

    existing_tx_by_hash = {
        t.import_hash: t
        for t in db.execute(select(Transaction)).scalars().all()
    }
    cat_by_id_all = {c.id: c for c in db.execute(select(Category)).scalars().all()} if is_v3 else {}
    for et in export.transactions:
        existing = existing_tx_by_hash.get(et.import_hash)
        if existing is not None:
            preview.will_skip_transactions += 1
            if len(preview.skip_transactions) < PREVIEW_SAMPLE_LIMIT:
                preview.skip_transactions.append(TransactionPreview(
                    import_hash=et.import_hash, datum=et.datum, bedrag=et.bedrag,
                    merchant_name=et.merchant_name, omschrijving=et.omschrijving,
                ))
            if is_v3:
                existing_cat_name = (
                    full_category_path(existing.category_id, cat_by_id_all)
                    if existing.category_id else None
                )
            else:
                existing_cat_name = existing.category.name if existing.category else None
            cat_diff = (existing_cat_name or None) != (et.category_name or None)
            merchant_diff = (existing.merchant_name or None) != (et.merchant_name or None)
            if cat_diff or merchant_diff:
                preview.will_update_transactions += 1
                if len(preview.update_transactions) < PREVIEW_SAMPLE_LIMIT:
                    preview.update_transactions.append(TransactionUpdatePreview(
                        import_hash=et.import_hash, datum=et.datum, bedrag=et.bedrag,
                        omschrijving=et.omschrijving,
                        old_category_name=existing_cat_name,
                        new_category_name=et.category_name,
                        old_merchant_name=existing.merchant_name,
                        new_merchant_name=et.merchant_name,
                    ))
            # format_version 1 files predate flags entirely; their absent
            # fields default to False/None, which must never be treated as
            # an incoming change or flagged as a conflict against curated data.
            if export.format_version != 1:
                existing_flags_default = (
                    not existing.is_internal_transfer
                    and not existing.is_internal_transfer_manual
                    and not existing.is_incidental
                    and existing.incidental_label_id is None
                )
                existing_label_name = (
                    label_name_by_id.get(existing.incidental_label_id)
                    if existing.incidental_label_id else None
                )
                flags_differ = (
                    existing.is_internal_transfer != et.is_internal_transfer
                    or existing.is_internal_transfer_manual != et.is_internal_transfer_manual
                    or existing.is_incidental != et.is_incidental
                    or existing_label_name != et.incidental_label
                )
                if not existing_flags_default and flags_differ:
                    preview.soft_conflicts.append(ImportConflict(
                        code="transaction_flags_conflict", severity="soft",
                        message=(
                            f"Transaction {et.import_hash} has curated flags on destination; "
                            "imported flags not applied."
                        ),
                    ))
        else:
            preview.will_add_transactions += 1
            if len(preview.add_transactions) < PREVIEW_SAMPLE_LIMIT:
                preview.add_transactions.append(TransactionPreview(
                    import_hash=et.import_hash, datum=et.datum, bedrag=et.bedrag,
                    merchant_name=et.merchant_name, omschrijving=et.omschrijving,
                ))

    income_locked = set(db.execute(
        select(TransactionOffset.income_transaction_id)
    ).scalars().all())
    income_hash_locked = set()
    if income_locked:
        rows = db.execute(
            select(Transaction.id, Transaction.import_hash).where(Transaction.id.in_(income_locked))
        ).all()
        income_hash_locked = {h for _, h in rows}
    for eo in export.transaction_offsets:
        if eo.income_import_hash in income_hash_locked:
            preview.soft_conflicts.append(ImportConflict(
                code="offset_income_locked", severity="soft",
                message=f"Income transaction {eo.income_import_hash} already linked on destination; offset skipped.",
            ))
        else:
            preview.will_add_offsets += 1

    if export.sync_events:
        applied_event_ids = set(
            db.execute(select(SyncEvent.event_id)).scalars().all()
        )
        for ev in export.sync_events:
            if ev.event_id in applied_event_ids:
                preview.will_skip_sync_events += 1
            else:
                preview.will_apply_sync_events += 1

    if export.receipts:
        # A linked receipt is skipped if the destination's matching transaction
        # already has a receipt, or if the transaction doesn't exist yet. A
        # standalone receipt (no transaction) is skipped only if an existing
        # standalone receipt matches it exactly.
        dest_tx_with_receipt = set(db.execute(
            select(Transaction.import_hash).where(
                select(Receipt.id).where(Receipt.transaction_id == Transaction.id).exists()
            )
        ).scalars().all())
        existing_standalone_keys = {
            _standalone_receipt_key(r)
            for r in db.execute(
                select(Receipt).where(Receipt.transaction_id.is_(None))
            ).scalars().all()
        }
        for er in export.receipts:
            if er.transaction_import_hash is None:
                if _standalone_receipt_key(er) in existing_standalone_keys:
                    preview.will_skip_receipts += 1
                else:
                    preview.will_add_receipts += 1
            elif er.transaction_import_hash in dest_tx_with_receipt:
                preview.will_skip_receipts += 1
            else:
                preview.will_add_receipts += 1

    return preview


def _standalone_receipt_key(receipt) -> tuple:
    """Identity key for deduplicating standalone receipts (no transaction_id)
    on (date, total_amount, merchant_name, ocr_raw_text)."""
    return (receipt.date, receipt.total_amount, receipt.merchant_name, receipt.ocr_raw_text)


def _apply_receipts(
    db: Session,
    receipts: list[ExportReceipt],
    tx_by_hash: dict[str, Transaction],
    cat_idx: dict[str, Category],
    format_version: int,
) -> None:
    """Insert receipts (with their line items + image files) for transactions
    that don't yet have one on the destination. NAS-wins on existing receipts.

    Standalone receipts (transaction_import_hash is None) are inserted unless
    an existing standalone receipt matches exactly on
    (date, total_amount, merchant_name, ocr_raw_text)."""
    existing_standalone_keys = {
        _standalone_receipt_key(r)
        for r in db.execute(
            select(Receipt).where(Receipt.transaction_id.is_(None))
        ).scalars().all()
    }
    for er in receipts:
        tx_id = None
        if er.transaction_import_hash is None:
            key = _standalone_receipt_key(er)
            if key in existing_standalone_keys:
                continue
        else:
            tx = tx_by_hash.get(er.transaction_import_hash)
            if tx is None:
                continue
            existing = db.execute(
                select(Receipt).where(Receipt.transaction_id == tx.id)
            ).scalar_one_or_none()
            if existing is not None:
                continue
            tx_id = tx.id

        relative_path = None
        if er.image_base64 and er.image_filename:
            # Place inside uploads/sync/<imported-yyyy-mm>/ to keep imports separate
            stamp = datetime.now(timezone.utc)
            target_dir = Path(UPLOADS_DIR) / "sync" / f"{stamp.year}" / f"{stamp.month:02d}"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / er.image_filename
            # If a file with this name already exists, suffix to avoid clobbering
            if target.exists():
                stem = target.stem
                suffix = target.suffix
                idx = 1
                while target.exists():
                    target = target_dir / f"{stem}-{idx}{suffix}"
                    idx += 1
            target.write_bytes(base64.b64decode(er.image_base64))
            relative_path = str(target.relative_to(UPLOADS_DIR))

        receipt = Receipt(
            transaction_id=tx_id,
            date=er.date,
            total_amount=er.total_amount,
            merchant_name=er.merchant_name,
            image_path=relative_path,
            ocr_raw_text=er.ocr_raw_text,
            match_confidence=er.match_confidence,
            created_at=er.created_at.replace(tzinfo=None) if er.created_at.tzinfo else er.created_at,
        )
        db.add(receipt)
        db.flush()

        if er.transaction_import_hash is None:
            existing_standalone_keys.add(_standalone_receipt_key(er))

        for eli in er.line_items:
            cat = _lookup_category_ref(eli.category_name, format_version, cat_idx, db)
            db.add(LineItem(
                receipt_id=receipt.id,
                description=eli.description,
                amount=eli.amount,
                quantity=eli.quantity,
                category_id=cat.id if cat else None,
                sort_order=eli.sort_order,
                is_remaining=eli.is_remaining,
            ))


def _apply_sync_event(db: Session, ev: ExportSyncEvent, conflicts: list[ImportConflict]) -> None:
    """Apply a single sync event to the destination DB. Missing entities are no-ops.

    Rename/delete/merge/update events carry both name and path fields
    (format v3 writes both; v1/v2 replays only ever have names). Path
    fields are preferred when present -- they unambiguously identify a
    category even when its bare name collides with a same-named category
    under a different parent -- falling back to the bare-name lookup
    otherwise. Every bare-name lookup goes through
    `_find_category_by_name_safe`, which never raises: zero matches is a
    normal no-op, and multiple matches (now possible with per-parent
    names) is skipped with a soft conflict rather than guessing.
    """
    payload = ev.payload
    if ev.event_type == "category.rename":
        old_path = payload.get("old_path")
        new_path = payload.get("new_path")
        if old_path:
            cat = _category_path_index(db).get(old_path)
        else:
            cat = _find_category_by_name_safe(db, payload["old_name"], conflicts, "category rename")
        if cat is None:
            return
        if new_path:
            new_name = split_category_path(new_path)[-1]
            clash = _category_path_index(db).get(new_path)
        else:
            new_name = payload["new_name"]
            clash = _find_category_by_name_safe(db, new_name, conflicts, "category rename")
        # If a category already at the target identity exists, skip the rename
        if clash is not None and clash.id != cat.id:
            return
        cat.name = new_name
    elif ev.event_type == "category.delete":
        path = payload.get("path")
        if path:
            cat = _category_path_index(db).get(path)
        else:
            cat = _find_category_by_name_safe(db, payload["name"], conflicts, "category delete")
        if cat is None:
            return
        # Mirror settings.py delete_all_categories cleanup for FK safety
        db.execute(sa_delete(CategoryMapping).where(CategoryMapping.category_id == cat.id))
        db.execute(sa_delete(BudgetTemplate).where(BudgetTemplate.category_id == cat.id))
        db.execute(sa_delete(BudgetLine).where(BudgetLine.category_id == cat.id))
        db.execute(sa_update(LineItem).where(LineItem.category_id == cat.id).values(category_id=None))
        db.execute(sa_update(Transaction).where(Transaction.category_id == cat.id).values(category_id=None))
        # If any other category points to this as parent, nullify
        db.execute(sa_update(Category).where(Category.parent_id == cat.id).values(parent_id=None))
        db.delete(cat)
    elif ev.event_type == "category.update":
        path = payload.get("path")
        if path:
            cat = _category_path_index(db).get(path)
        else:
            cat = _find_category_by_name_safe(db, payload["name"], conflicts, "category update")
        if cat is None:
            return
        cat.is_fixed = payload.get("is_fixed", cat.is_fixed)
        cat.category_type = payload.get("category_type", cat.category_type)
        if "parent_path" in payload:
            parent_path = payload["parent_path"]
            if parent_path is None:
                cat.parent_id = None
            else:
                parent = _category_path_index(db).get(parent_path)
                if parent is not None:
                    cat.parent_id = parent.id
        else:
            parent_name = payload.get("parent_name")
            if parent_name is None:
                cat.parent_id = None
            else:
                parent = _find_category_by_name_safe(db, parent_name, conflicts, "category update parent")
                if parent is not None:
                    cat.parent_id = parent.id
    elif ev.event_type == "category.merge":
        source_path = payload.get("source_path")
        target_path = payload.get("target_path")
        if source_path or target_path:
            path_idx = _category_path_index(db)
            source = path_idx.get(source_path) if source_path else None
            target = path_idx.get(target_path) if target_path else None
        else:
            source = _find_category_by_name_safe(db, payload["source_name"], conflicts, "category merge")
            target = _find_category_by_name_safe(db, payload["target_name"], conflicts, "category merge")
        if source is None or target is None:
            return
        apply_category_merge(db, source, target)
    elif ev.event_type == "category_mapping.delete":
        m = db.execute(
            select(CategoryMapping).where(CategoryMapping.bank_category == payload["bank_category"])
        ).scalar_one_or_none()
        if m is not None:
            db.delete(m)
    elif ev.event_type == "budget.delete":
        from datetime import date as _date
        start = _date.fromisoformat(payload["start_date"])
        budget = db.execute(
            select(Budget).where(Budget.start_date == start)
        ).scalar_one_or_none()
        if budget is not None:
            db.delete(budget)
    # Unknown event types are ignored (forward compat)


def commit_import(db: Session, export: ExportFile, update_duplicates: bool) -> ImportPreview:
    preview = preview_import(db, export)
    if preview.hard_conflicts:
        raise ValueError(
            f"Import aborted by {len(preview.hard_conflicts)} hard conflict(s): "
            + "; ".join(c.message for c in preview.hard_conflicts)
        )

    # 0. Apply sync events first (renames + deletes), so the additive merge
    #    that follows sees the post-mutation state.
    if export.sync_events:
        applied_event_ids = set(
            db.execute(select(SyncEvent.event_id)).scalars().all()
        )
        # Sort by created_at to apply in original order
        ordered_events = sorted(export.sync_events, key=lambda e: e.created_at)
        for ev in ordered_events:
            if ev.event_id in applied_event_ids:
                continue
            _apply_sync_event(db, ev, preview.soft_conflicts)
            db.add(SyncEvent(
                event_id=ev.event_id,
                event_type=ev.event_type,
                payload_json=json.dumps(ev.payload),
                created_at=ev.created_at.replace(tzinfo=None) if ev.created_at.tzinfo else ev.created_at,
            ))
        db.flush()

    # 1. Categories -- insert missing.
    is_v3 = export.format_version == 3
    if is_v3:
        # Path-keyed: process shallowest paths first so a category's own
        # export entry always creates it with its *real* attributes before
        # any deeper path could reference it as an (otherwise default-typed)
        # missing ancestor.
        cat_idx = _category_path_index(db)
        sorted_cats = sorted(
            export.categories, key=lambda c: len(split_category_path(c.path or c.name))
        )
        for ec in sorted_cats:
            effective_path = ec.path or ec.name
            if effective_path in cat_idx:
                continue
            segments = split_category_path(effective_path)
            parent = None
            if len(segments) > 1:
                parent_path = PATH_SEPARATOR.join(segments[:-1])
                parent = cat_idx.get(parent_path)
                if parent is None:
                    parent = resolve_or_create_category_path(db, parent_path, cat_idx)
            new_cat = Category(
                name=segments[-1], parent_id=parent.id if parent else None,
                is_fixed=ec.is_fixed, category_type=ec.category_type,
            )
            db.add(new_cat)
            db.flush()
            cat_idx[effective_path] = new_cat
    else:
        # Name-keyed, two passes (parents first via topological sort).
        cat_idx = _category_index(db)
        inserted_round = True
        pending = list(export.categories)
        while pending and inserted_round:
            inserted_round = False
            remaining = []
            for ec in pending:
                if ec.name in cat_idx:
                    continue
                parent_id = None
                if ec.parent_name is not None:
                    parent = cat_idx.get(ec.parent_name)
                    if parent is None:
                        remaining.append(ec)
                        continue
                    parent_id = parent.id
                new_cat = Category(
                    name=ec.name, parent_id=parent_id,
                    is_fixed=ec.is_fixed, category_type=ec.category_type,
                )
                db.add(new_cat)
                db.flush()
                cat_idx[ec.name] = new_cat
                inserted_round = True
            pending = remaining
        if pending:
            raise ValueError(f"Could not resolve parents for: {[c.name for c in pending]}")

    # 2. Category mappings -- insert missing only (NAS-wins on existing)
    existing_mappings = {m.bank_category for m in db.execute(select(CategoryMapping)).scalars().all()}
    for em in export.category_mappings:
        if em.bank_category in existing_mappings:
            continue
        cat = _lookup_category_ref(em.category_name, export.format_version, cat_idx, db)
        if cat is None:
            continue
        db.add(CategoryMapping(bank_category=em.bank_category, category_id=cat.id))

    # 3. Budgets -- insert missing (overlap pre-validated above)
    bud_idx = _budget_index(db)
    for eb in export.budgets:
        key = eb.start_date.isoformat()
        if key in bud_idx:
            continue
        new_b = Budget(start_date=eb.start_date, end_date=eb.end_date)
        db.add(new_b)
        db.flush()
        bud_idx[key] = new_b

    # 4. Budget lines -- local-wins on amount conflict (S2)
    existing_lines = {
        (l.budget_id, l.category_id): l
        for l in db.execute(select(BudgetLine)).scalars().all()
    }
    for el in export.budget_lines:
        budget = bud_idx.get(el.budget_start_date.isoformat())
        cat = _lookup_category_ref(el.category_name, export.format_version, cat_idx, db)
        if budget is None or cat is None:
            continue
        existing = existing_lines.get((budget.id, cat.id))
        if existing is None:
            db.add(BudgetLine(
                budget_id=budget.id, category_id=cat.id, amount=el.amount, source=el.source,
            ))
        else:
            existing.amount = el.amount
            existing.source = el.source

    # 5. Budget templates -- NAS-wins on conflict (S3)
    existing_template_cat_ids = {
        t.category_id for t in db.execute(select(BudgetTemplate)).scalars().all()
    }
    for et in export.budget_templates:
        cat = _lookup_category_ref(et.category_name, export.format_version, cat_idx, db)
        if cat is None or cat.id in existing_template_cat_ids:
            continue
        db.add(BudgetTemplate(category_id=cat.id, amount=et.amount))

    # 5b. Incidental labels -- insert missing by name
    label_idx = _incidental_label_index(db)
    label_names_needed = set(export.incidental_labels) | {
        et.incidental_label for et in export.transactions if et.incidental_label
    }
    for name in label_names_needed:
        if name in label_idx:
            continue
        new_label = IncidentalLabel(name=name)
        db.add(new_label)
        db.flush()
        label_idx[name] = new_label

    # 5c. Own accounts -- insert missing by IBAN; existing IBAN is left untouched
    existing_accounts_by_iban = {
        a.iban: a for a in db.execute(select(OwnAccount)).scalars().all()
    }
    for ea in export.own_accounts:
        if ea.iban in existing_accounts_by_iban:
            continue
        new_account = OwnAccount(
            iban=ea.iban, name=ea.name, account_type=ea.account_type,
            starting_balance=ea.starting_balance,
            starting_balance_date=ea.starting_balance_date,
        )
        db.add(new_account)
        existing_accounts_by_iban[ea.iban] = new_account

    # 5d. Allocation buckets -- upsert by name; imported positions are
    # relative order only: file order first, then local-only buckets, all
    # rewritten 0..n-1 (spec: salary allocation design, "Sync").
    if export.allocation_buckets:
        existing_buckets_by_name = {
            b.name: b for b in db.execute(select(AllocationBucket)).scalars().all()
        }
        imported_names: list[str] = []
        for eb in export.allocation_buckets:
            ref_cat = _lookup_category_ref(eb.category_path, export.format_version, cat_idx, db)
            bucket = existing_buckets_by_name.get(eb.name)
            if bucket is None:
                bucket = AllocationBucket(
                    name=eb.name, rule_type=eb.rule_type, value=eb.value,
                    position=0, is_active=eb.is_active,
                    category_id=ref_cat.id if ref_cat else None,
                )
                db.add(bucket)
                existing_buckets_by_name[eb.name] = bucket
            else:
                bucket.rule_type = eb.rule_type
                bucket.value = eb.value
                bucket.is_active = eb.is_active
                bucket.category_id = ref_cat.id if ref_cat else None
            imported_names.append(eb.name)
        db.flush()
        local_only = [
            b for b in sorted(
                existing_buckets_by_name.values(), key=lambda b: (b.position, b.id or 0)
            )
            if b.name not in set(imported_names)
        ]
        ordered = [existing_buckets_by_name[n] for n in imported_names] + local_only
        for i, bucket in enumerate(ordered):
            bucket.position = i

    # 6. Transactions
    existing_tx = {
        t.import_hash: t
        for t in db.execute(select(Transaction)).scalars().all()
    }
    for et in export.transactions:
        label_id = (
            label_idx[et.incidental_label].id
            if et.incidental_label and et.incidental_label in label_idx
            else None
        )
        if et.import_hash in existing_tx:
            tx = existing_tx[et.import_hash]
            if update_duplicates:
                tx.merchant_name = et.merchant_name
                ref_cat = _lookup_category_ref(et.category_name, export.format_version, cat_idx, db)
                tx.category_id = ref_cat.id if ref_cat else None
            # format_version 1 files carry no real flag information (absent
            # fields default to False/None); never let them touch an
            # existing transaction's flags, curated or not.
            if export.format_version != 1:
                existing_flags_default = (
                    not tx.is_internal_transfer
                    and not tx.is_internal_transfer_manual
                    and not tx.is_incidental
                    and tx.incidental_label_id is None
                )
                if existing_flags_default:
                    tx.is_internal_transfer = et.is_internal_transfer
                    tx.is_internal_transfer_manual = et.is_internal_transfer_manual
                    tx.is_incidental = et.is_incidental
                    tx.incidental_label_id = label_id
            continue
        ref_cat = _lookup_category_ref(et.category_name, export.format_version, cat_idx, db)
        category_id = ref_cat.id if ref_cat else None
        new_tx = Transaction(
            datum=et.datum, rekening=et.rekening, tegenrekening=et.tegenrekening,
            naam=et.naam, adres=et.adres, postcode=et.postcode, woonplaats=et.woonplaats,
            valuta_saldo=et.valuta_saldo, saldo_voor_boeking=et.saldo_voor_boeking,
            valuta=et.valuta, bedrag=et.bedrag, verwerkingsdatum=et.verwerkingsdatum,
            valutadatum=et.valutadatum, code=et.code, type=et.type,
            volgnummer=et.volgnummer, betalingskenmerk=et.betalingskenmerk,
            omschrijving=et.omschrijving, afschriftnummer=et.afschriftnummer,
            categorie=et.categorie, merchant_name=et.merchant_name,
            import_hash=et.import_hash, created_at=et.created_at, category_id=category_id,
            is_internal_transfer=et.is_internal_transfer,
            is_internal_transfer_manual=et.is_internal_transfer_manual,
            is_incidental=et.is_incidental,
            incidental_label_id=label_id,
        )
        db.add(new_tx)
        db.flush()
        existing_tx[et.import_hash] = new_tx

    # 7. Offsets -- skip if income tx already linked
    income_locked_ids = set(db.execute(
        select(TransactionOffset.income_transaction_id)
    ).scalars().all())
    for eo in export.transaction_offsets:
        expense = existing_tx.get(eo.expense_import_hash)
        income = existing_tx.get(eo.income_import_hash)
        if expense is None or income is None:
            continue
        if income.id in income_locked_ids:
            continue
        db.add(TransactionOffset(
            expense_transaction_id=expense.id, income_transaction_id=income.id,
        ))
        income_locked_ids.add(income.id)

    # 7b. Receipts -- create only if the transaction has no receipt yet (NAS-wins)
    if export.receipts:
        _apply_receipts(db, export.receipts, existing_tx, cat_idx, export.format_version)

    # 8. Record this export as imported (idempotency audit)
    if export.export_id:
        already = db.execute(
            select(ImportedExport).where(ImportedExport.export_id == export.export_id)
        ).scalar_one_or_none()
        if already is None:
            db.add(ImportedExport(
                export_id=export.export_id,
                transactions_added=preview.will_add_transactions,
                transactions_updated=preview.will_update_transactions,
                categories_added=preview.will_add_categories,
            ))

    db.commit()
    return preview


BACKUP_RETENTION_COUNT = 10


def snapshot_sqlite_db(db_path: Path, backup_dir: Path) -> str | None:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%fZ")
    target = backup_dir / f"{db_path.stem}-pre-import-{stamp}.db"
    shutil.copy2(db_path, target)
    _prune_old_backups(backup_dir, db_path.stem)
    return str(target)


def _prune_old_backups(backup_dir: Path, db_stem: str) -> None:
    """Keep only the BACKUP_RETENTION_COUNT most recent pre-import backups."""
    pattern = f"{db_stem}-pre-import-*.db"
    backups = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
    excess = len(backups) - BACKUP_RETENTION_COUNT
    if excess <= 0:
        return
    for stale in backups[:excess]:
        stale.unlink(missing_ok=True)
