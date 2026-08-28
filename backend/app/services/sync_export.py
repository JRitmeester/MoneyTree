import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

import base64
import json
from pathlib import Path

from ..config import UPLOADS_DIR
from ..models import (
    Budget, BudgetLine, BudgetTemplate, Category, CategoryMapping,
    AllocationBucket, IncidentalLabel, LineItem, OwnAccount, Receipt, SyncEvent, Transaction,
    TransactionOffset,
)
from .category_paths import full_category_path
from ..sync_schemas import (
    ExportBudget, ExportBudgetLine, ExportBudgetTemplate, ExportCategory,
    ExportAllocationBucket, ExportCategoryMapping, ExportFile, ExportLineItem, ExportOwnAccount,
    ExportReceipt, ExportSyncEvent, ExportTransaction, ExportTransactionOffset,
)


def build_export(db: Session, since: Optional[date]) -> ExportFile:
    cats = db.execute(select(Category)).scalars().all()
    cat_by_id = {c.id: c for c in cats}

    export_categories = [
        ExportCategory(
            name=c.name,
            parent_name=cat_by_id[c.parent_id].name if c.parent_id else None,
            is_fixed=c.is_fixed,
            category_type=c.category_type,
            path=full_category_path(c.id, cat_by_id),
        )
        for c in cats
    ]

    mappings = db.execute(select(CategoryMapping)).scalars().all()
    export_mappings = [
        ExportCategoryMapping(
            bank_category=m.bank_category,
            category_name=full_category_path(m.category_id, cat_by_id),
        )
        for m in mappings
    ]

    budgets = db.execute(select(Budget)).scalars().all()
    budget_by_id = {b.id: b for b in budgets}
    export_budgets = [
        ExportBudget(start_date=b.start_date, end_date=b.end_date) for b in budgets
    ]

    lines = db.execute(select(BudgetLine)).scalars().all()
    export_lines = [
        ExportBudgetLine(
            budget_start_date=budget_by_id[l.budget_id].start_date,
            category_name=full_category_path(l.category_id, cat_by_id),
            amount=l.amount,
            source=l.source,
        )
        for l in lines
    ]

    templates = db.execute(select(BudgetTemplate)).scalars().all()
    export_templates = [
        ExportBudgetTemplate(
            category_name=full_category_path(t.category_id, cat_by_id),
            amount=t.amount,
        )
        for t in templates
    ]

    tx_query = select(Transaction)
    if since is not None:
        cutoff = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
        # Filter by updated_at so transactions edited (recategorized) during the
        # outage are included even if they were originally imported earlier.
        tx_query = tx_query.where(Transaction.updated_at >= cutoff)
    txs = db.execute(tx_query).scalars().all()
    tx_by_id = {t.id: t for t in txs}

    labels = db.execute(select(IncidentalLabel)).scalars().all()
    label_by_id = {l.id: l for l in labels}
    export_incidental_labels = [l.name for l in labels]

    export_txs = [
        ExportTransaction(
            import_hash=t.import_hash,
            datum=t.datum,
            rekening=t.rekening,
            tegenrekening=t.tegenrekening,
            naam=t.naam,
            adres=t.adres,
            postcode=t.postcode,
            woonplaats=t.woonplaats,
            valuta_saldo=t.valuta_saldo,
            saldo_voor_boeking=t.saldo_voor_boeking,
            valuta=t.valuta,
            bedrag=t.bedrag,
            verwerkingsdatum=t.verwerkingsdatum,
            valutadatum=t.valutadatum,
            code=t.code,
            type=t.type,
            volgnummer=t.volgnummer,
            betalingskenmerk=t.betalingskenmerk,
            omschrijving=t.omschrijving,
            afschriftnummer=t.afschriftnummer,
            categorie=t.categorie,
            merchant_name=t.merchant_name,
            category_name=full_category_path(t.category_id, cat_by_id) if t.category_id else None,
            created_at=t.created_at,
            is_internal_transfer=t.is_internal_transfer,
            is_internal_transfer_manual=t.is_internal_transfer_manual,
            is_incidental=t.is_incidental,
            incidental_label=(
                label_by_id[t.incidental_label_id].name
                if t.incidental_label_id else None
            ),
        )
        for t in txs
    ]

    own_accounts = db.execute(select(OwnAccount)).scalars().all()
    export_own_accounts = [
        ExportOwnAccount(
            iban=a.iban,
            name=a.name,
            account_type=a.account_type,
            starting_balance=a.starting_balance,
            starting_balance_date=a.starting_balance_date,
        )
        for a in own_accounts
    ]

    buckets = db.execute(
        select(AllocationBucket).order_by(AllocationBucket.position, AllocationBucket.id)
    ).scalars().all()
    export_allocation_buckets = [
        ExportAllocationBucket(
            name=b.name,
            rule_type=b.rule_type,
            value=b.value,
            position=b.position,
            is_active=b.is_active,
            category_path=(
                full_category_path(b.category_id, cat_by_id)
                if b.category_id is not None
                else None
            ),
        )
        for b in buckets
    ]

    tx_ids = set(tx_by_id.keys())
    offsets = db.execute(select(TransactionOffset)).scalars().all()
    export_offsets = [
        ExportTransactionOffset(
            expense_import_hash=tx_by_id[o.expense_transaction_id].import_hash,
            income_import_hash=tx_by_id[o.income_transaction_id].import_hash,
        )
        for o in offsets
        if o.expense_transaction_id in tx_ids and o.income_transaction_id in tx_ids
    ]

    # Receipts: those linked to a transaction we're exporting, plus standalone
    # receipts (no transaction_id), which travel with a null transaction hash.
    export_receipts = []
    receipts = db.execute(select(Receipt)).scalars().all()
    for r in receipts:
        if r.transaction_id is not None:
            tx = tx_by_id.get(r.transaction_id)
            if tx is None:
                continue
            import_hash = tx.import_hash
        else:
            import_hash = None

        image_b64 = None
        image_filename = None
        if r.image_path:
            full_path = Path(UPLOADS_DIR) / r.image_path
            if full_path.is_file():
                image_filename = Path(r.image_path).name
                image_b64 = base64.b64encode(full_path.read_bytes()).decode("ascii")
        li_rows = db.execute(
            select(LineItem).where(LineItem.receipt_id == r.id).order_by(LineItem.sort_order)
        ).scalars().all()
        export_line_items = [
            ExportLineItem(
                description=li.description,
                amount=li.amount,
                quantity=li.quantity,
                category_name=full_category_path(li.category_id, cat_by_id) if li.category_id else None,
                sort_order=li.sort_order,
                is_remaining=li.is_remaining,
            )
            for li in li_rows
        ]
        export_receipts.append(ExportReceipt(
            transaction_import_hash=import_hash,
            date=r.date,
            total_amount=r.total_amount,
            merchant_name=r.merchant_name,
            image_filename=image_filename,
            image_base64=image_b64,
            ocr_raw_text=r.ocr_raw_text,
            match_confidence=r.match_confidence,
            created_at=r.created_at,
            line_items=export_line_items,
            ))

    event_query = select(SyncEvent).order_by(SyncEvent.created_at)
    if since is not None:
        cutoff = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
        event_query = event_query.where(SyncEvent.created_at >= cutoff)
    events = db.execute(event_query).scalars().all()
    export_events = [
        ExportSyncEvent(
            event_id=e.event_id,
            event_type=e.event_type,
            payload=json.loads(e.payload_json),
            created_at=e.created_at,
        )
        for e in events
    ]

    return ExportFile(
        format_version=3,
        export_id=str(uuid.uuid4()),
        exported_at=datetime.now(timezone.utc),
        since=since,
        categories=export_categories,
        category_mappings=export_mappings,
        budgets=export_budgets,
        budget_lines=export_lines,
        budget_templates=export_templates,
        transactions=export_txs,
        transaction_offsets=export_offsets,
        receipts=export_receipts,
        sync_events=export_events,
        incidental_labels=export_incidental_labels,
        own_accounts=export_own_accounts,
        allocation_buckets=export_allocation_buckets,
    )
