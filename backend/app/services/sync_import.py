import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Budget, BudgetLine, BudgetTemplate, Category, CategoryMapping,
    ImportedExport, Transaction, TransactionOffset,
)
from ..sync_schemas import (
    ExportFile, ImportConflict, ImportPreview,
    PREVIEW_SAMPLE_LIMIT, TransactionPreview, TransactionUpdatePreview,
)


def _category_index(db: Session) -> dict[str, Category]:
    return {c.name: c for c in db.execute(select(Category)).scalars().all()}


def _budget_index(db: Session) -> dict[str, Budget]:
    return {b.start_date.isoformat(): b for b in db.execute(select(Budget)).scalars().all()}


def _tx_hashes(db: Session) -> set[str]:
    return set(db.execute(select(Transaction.import_hash)).scalars().all())


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

    cat_idx = _category_index(db)
    for ec in export.categories:
        existing = cat_idx.get(ec.name)
        if existing is None:
            preview.will_add_categories += 1
            if len(preview.add_categories) < PREVIEW_SAMPLE_LIMIT:
                preview.add_categories.append(ec.name)
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

    # Validate parent_name resolves
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
        category = cat_idx.get(el.category_name)
        if budget is None or category is None:
            preview.will_add_budget_lines += 1
            continue
        if (budget.id, category.id) in line_keys:
            preview.will_update_budget_lines += 1
        else:
            preview.will_add_budget_lines += 1

    tmpl_cat_ids = {t.category_id for t in db.execute(select(BudgetTemplate)).scalars().all()}
    for et in export.budget_templates:
        cat = cat_idx.get(et.category_name)
        if cat is None or cat.id not in tmpl_cat_ids:
            preview.will_add_budget_templates += 1
        else:
            preview.soft_conflicts.append(ImportConflict(
                code="template_conflict", severity="soft",
                message=f"BudgetTemplate for '{et.category_name}' exists; NAS amount kept.",
            ))

    existing_tx_by_hash = {
        t.import_hash: t
        for t in db.execute(select(Transaction)).scalars().all()
    }
    for et in export.transactions:
        existing = existing_tx_by_hash.get(et.import_hash)
        if existing is not None:
            preview.will_skip_transactions += 1
            if len(preview.skip_transactions) < PREVIEW_SAMPLE_LIMIT:
                preview.skip_transactions.append(TransactionPreview(
                    import_hash=et.import_hash, datum=et.datum, bedrag=et.bedrag,
                    merchant_name=et.merchant_name, omschrijving=et.omschrijving,
                ))
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

    return preview


def commit_import(db: Session, export: ExportFile, update_duplicates: bool) -> ImportPreview:
    preview = preview_import(db, export)
    if preview.hard_conflicts:
        raise ValueError(
            f"Import aborted by {len(preview.hard_conflicts)} hard conflict(s): "
            + "; ".join(c.message for c in preview.hard_conflicts)
        )

    # 1. Categories -- insert missing, in two passes (parents first via topological sort)
    cat_idx = _category_index(db)
    by_name = {c.name: c for c in export.categories}
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
        cat = cat_idx.get(em.category_name)
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
        cat = cat_idx.get(el.category_name)
        if budget is None or cat is None:
            continue
        existing = existing_lines.get((budget.id, cat.id))
        if existing is None:
            db.add(BudgetLine(budget_id=budget.id, category_id=cat.id, amount=el.amount))
        else:
            existing.amount = el.amount

    # 5. Budget templates -- NAS-wins on conflict (S3)
    existing_template_cat_ids = {
        t.category_id for t in db.execute(select(BudgetTemplate)).scalars().all()
    }
    for et in export.budget_templates:
        cat = cat_idx.get(et.category_name)
        if cat is None or cat.id in existing_template_cat_ids:
            continue
        db.add(BudgetTemplate(category_id=cat.id, amount=et.amount))

    # 6. Transactions
    existing_tx = {
        t.import_hash: t
        for t in db.execute(select(Transaction)).scalars().all()
    }
    for et in export.transactions:
        if et.import_hash in existing_tx:
            if update_duplicates:
                tx = existing_tx[et.import_hash]
                tx.merchant_name = et.merchant_name
                tx.category_id = cat_idx[et.category_name].id if et.category_name and et.category_name in cat_idx else None
            continue
        category_id = (
            cat_idx[et.category_name].id
            if et.category_name and et.category_name in cat_idx
            else None
        )
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
