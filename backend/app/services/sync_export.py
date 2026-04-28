import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Budget, BudgetLine, BudgetTemplate, Category, CategoryMapping,
    Transaction, TransactionOffset,
)
from ..sync_schemas import (
    ExportBudget, ExportBudgetLine, ExportBudgetTemplate, ExportCategory,
    ExportCategoryMapping, ExportFile, ExportTransaction, ExportTransactionOffset,
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
        )
        for c in cats
    ]

    mappings = db.execute(select(CategoryMapping)).scalars().all()
    export_mappings = [
        ExportCategoryMapping(
            bank_category=m.bank_category,
            category_name=cat_by_id[m.category_id].name,
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
            category_name=cat_by_id[l.category_id].name,
            amount=l.amount,
        )
        for l in lines
    ]

    templates = db.execute(select(BudgetTemplate)).scalars().all()
    export_templates = [
        ExportBudgetTemplate(
            category_name=cat_by_id[t.category_id].name,
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
            category_name=cat_by_id[t.category_id].name if t.category_id else None,
            created_at=t.created_at,
        )
        for t in txs
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

    return ExportFile(
        format_version=1,
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
    )
