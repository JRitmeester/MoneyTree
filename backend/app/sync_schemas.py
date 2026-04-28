from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


SUPPORTED_FORMAT_VERSIONS = {1}


class ExportCategory(BaseModel):
    name: str
    parent_name: Optional[str] = None
    is_fixed: bool = False
    category_type: str = "expense"


class ExportCategoryMapping(BaseModel):
    bank_category: str
    category_name: str


class ExportBudget(BaseModel):
    start_date: date
    end_date: date


class ExportBudgetLine(BaseModel):
    budget_start_date: date
    category_name: str
    amount: float


class ExportBudgetTemplate(BaseModel):
    category_name: str
    amount: float


class ExportTransaction(BaseModel):
    import_hash: str
    datum: date
    rekening: str
    tegenrekening: Optional[str] = None
    naam: Optional[str] = None
    adres: Optional[str] = None
    postcode: Optional[str] = None
    woonplaats: Optional[str] = None
    valuta_saldo: str
    saldo_voor_boeking: float
    valuta: str
    bedrag: float
    verwerkingsdatum: date
    valutadatum: date
    code: str
    type: str
    volgnummer: str
    betalingskenmerk: Optional[str] = None
    omschrijving: str
    afschriftnummer: str
    categorie: str
    merchant_name: Optional[str] = None
    category_name: Optional[str] = None
    created_at: datetime


class ExportTransactionOffset(BaseModel):
    expense_import_hash: str
    income_import_hash: str


class ExportSyncEvent(BaseModel):
    event_id: str
    event_type: str
    payload: dict
    created_at: datetime


class ExportFile(BaseModel):
    format_version: Literal[1]
    export_id: Optional[str] = None
    exported_at: datetime
    since: Optional[date] = None
    categories: list[ExportCategory]
    category_mappings: list[ExportCategoryMapping]
    budgets: list[ExportBudget]
    budget_lines: list[ExportBudgetLine]
    budget_templates: list[ExportBudgetTemplate]
    transactions: list[ExportTransaction]
    transaction_offsets: list[ExportTransactionOffset]
    sync_events: list[ExportSyncEvent] = Field(default_factory=list)


class ImportConflict(BaseModel):
    code: str
    severity: Literal["soft", "hard"]
    message: str


class TransactionPreview(BaseModel):
    """A short summary of a transaction shown in the import preview."""
    import_hash: str
    datum: date
    bedrag: float
    merchant_name: Optional[str] = None
    omschrijving: str


class TransactionUpdatePreview(BaseModel):
    """A transaction whose mutable fields will be overwritten on import."""
    import_hash: str
    datum: date
    bedrag: float
    omschrijving: str
    old_category_name: Optional[str] = None
    new_category_name: Optional[str] = None
    old_merchant_name: Optional[str] = None
    new_merchant_name: Optional[str] = None


# Sample size for preview detail lists; counts above this go into *_truncated.
PREVIEW_SAMPLE_LIMIT = 100


class ImportPreview(BaseModel):
    will_add_categories: int = 0
    will_add_category_mappings: int = 0
    will_add_budgets: int = 0
    will_add_budget_lines: int = 0
    will_update_budget_lines: int = 0
    will_add_budget_templates: int = 0
    will_add_transactions: int = 0
    will_update_transactions: int = 0
    will_skip_transactions: int = 0
    will_add_offsets: int = 0
    will_apply_sync_events: int = 0
    will_skip_sync_events: int = 0
    add_categories: list[str] = Field(default_factory=list)
    add_transactions: list[TransactionPreview] = Field(default_factory=list)
    skip_transactions: list[TransactionPreview] = Field(default_factory=list)
    update_transactions: list[TransactionUpdatePreview] = Field(default_factory=list)
    sample_truncated_at: int = PREVIEW_SAMPLE_LIMIT
    soft_conflicts: list[ImportConflict] = Field(default_factory=list)
    hard_conflicts: list[ImportConflict] = Field(default_factory=list)


class ImportResult(BaseModel):
    preview: ImportPreview
    committed: bool
    backup_path: Optional[str] = None
