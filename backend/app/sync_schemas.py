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


class ImportConflict(BaseModel):
    code: str
    severity: Literal["soft", "hard"]
    message: str


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
    soft_conflicts: list[ImportConflict] = Field(default_factory=list)
    hard_conflicts: list[ImportConflict] = Field(default_factory=list)


class ImportResult(BaseModel):
    preview: ImportPreview
    committed: bool
    backup_path: Optional[str] = None
