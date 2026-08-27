from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# Alias to avoid Pydantic v2 field-name shadowing (a field named `date` with an
# Optional[date] annotation resolves the type to None when defaulted to None).
DateType = date


SUPPORTED_FORMAT_VERSIONS = {1, 2, 3}


class ExportCategory(BaseModel):
    name: str
    parent_name: Optional[str] = None
    is_fixed: bool = False
    category_type: str = "expense"
    # Authoritative in format_version 3: the full "Parent > Child" path,
    # using the same " > " separator as the dashboard/budget hierarchical
    # display. `name` is kept for backward tooling/display but is no longer
    # a unique identifier once categories share names across parents.
    path: Optional[str] = None


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
    is_internal_transfer: bool = False
    is_internal_transfer_manual: bool = False
    is_incidental: bool = False
    incidental_label: Optional[str] = None


class ExportOwnAccount(BaseModel):
    iban: str
    name: str
    account_type: str
    starting_balance: Optional[float] = None
    starting_balance_date: Optional[DateType] = None


class ExportLineItem(BaseModel):
    description: str
    amount: float
    quantity: int = 1
    category_name: Optional[str] = None
    sort_order: int = 0
    is_remaining: bool = False


class ExportReceipt(BaseModel):
    """A receipt, optionally linked to a transaction by import_hash.

    Standalone receipts (without an attached transaction) are included with
    `transaction_import_hash=None`; on import, a standalone receipt is
    skipped as a duplicate only if an existing receipt matches exactly on
    (date, total_amount, merchant_name, ocr_raw_text).
    """
    transaction_import_hash: Optional[str] = None
    date: Optional[DateType] = None
    total_amount: Optional[float] = None
    merchant_name: Optional[str] = None
    image_filename: Optional[str] = None
    image_base64: Optional[str] = None
    ocr_raw_text: Optional[str] = None
    match_confidence: Optional[float] = None
    created_at: datetime
    line_items: list[ExportLineItem] = Field(default_factory=list)


class ExportTransactionOffset(BaseModel):
    expense_import_hash: str
    income_import_hash: str


class ExportSyncEvent(BaseModel):
    event_id: str
    event_type: str
    payload: dict
    created_at: datetime


class ExportFile(BaseModel):
    format_version: Literal[1, 2, 3]
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
    receipts: list[ExportReceipt] = Field(default_factory=list)
    sync_events: list[ExportSyncEvent] = Field(default_factory=list)
    incidental_labels: list[str] = Field(default_factory=list)
    own_accounts: list[ExportOwnAccount] = Field(default_factory=list)


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
    will_add_receipts: int = 0
    will_skip_receipts: int = 0
    will_add_incidental_labels: int = 0
    will_add_own_accounts: int = 0
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
