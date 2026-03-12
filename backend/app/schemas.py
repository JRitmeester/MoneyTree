from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, model_validator

# Alias to avoid Pydantic v2 field-name shadowing (field named "date" with default
# None causes Pydantic to resolve the type annotation "date" as None).
DateType = date


# --- Transactions ---


class TransactionOut(BaseModel):
    id: int
    datum: date
    rekening: str
    tegenrekening: Optional[str]
    naam: Optional[str]
    bedrag: float
    valuta: str
    omschrijving: str
    categorie: str
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    merchant_name: Optional[str]
    type: str
    code: str
    has_receipt: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="wrap")
    @classmethod
    def _populate_category_name(cls, obj, handler):
        instance = handler(obj)
        if hasattr(obj, "category") and obj.category is not None:
            instance.category_name = obj.category.name
        return instance


class TransactionDetail(TransactionOut):
    adres: Optional[str]
    postcode: Optional[str]
    woonplaats: Optional[str]
    valuta_saldo: str
    saldo_voor_boeking: float
    verwerkingsdatum: date
    valutadatum: date
    volgnummer: str
    betalingskenmerk: Optional[str]
    afschriftnummer: str
    receipt: Optional["ReceiptOut"] = None
    line_items: list["LineItemOut"] = []
    offsets: list["TransactionOut"] = []
    offsets_expense: Optional["TransactionOut"] = None


class TransactionListResponse(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    per_page: int


class ImportResult(BaseModel):
    imported: int
    skipped_duplicates: int
    updated: int = 0
    matches: "MatchResult"


class MatchResult(BaseModel):
    auto_linked: int
    pending_confirmation: list["MatchCandidate"]


class MatchCandidate(BaseModel):
    receipt_id: int
    transaction_id: int
    confidence: float
    receipt_merchant: Optional[str]
    transaction_merchant: Optional[str]
    receipt_amount: Optional[float]
    transaction_amount: float


# --- Receipts ---


class ReceiptOut(BaseModel):
    id: int
    transaction_id: Optional[int]
    date: Optional[date]
    total_amount: Optional[float]
    merchant_name: Optional[str]
    image_path: Optional[str]
    match_confidence: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}


class ReceiptDetail(ReceiptOut):
    ocr_raw_text: Optional[str]
    line_items: list["LineItemOut"]
    transaction: Optional[TransactionOut] = None


class ReceiptUpdate(BaseModel):
    date: Optional[DateType] = None
    total_amount: Optional[float] = None
    merchant_name: Optional[str] = None


class OcrResult(BaseModel):
    date: Optional[str]
    total_amount: Optional[float]
    merchant_name: Optional[str]
    line_items: list["OcrLineItem"]
    raw_text: str


class OcrLineItem(BaseModel):
    description: str
    amount: float
    quantity: int = 1


class ReceiptCreateResponse(BaseModel):
    id: int
    image_path: str
    ocr_result: OcrResult


# --- Line Items ---


class LineItemOut(BaseModel):
    id: int
    receipt_id: int
    description: str
    amount: float
    quantity: int
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    sort_order: int
    is_remaining: bool = False

    model_config = {"from_attributes": True}

    @model_validator(mode="wrap")
    @classmethod
    def _populate_category_name(cls, obj, handler):
        instance = handler(obj)
        if hasattr(obj, "category") and obj.category is not None:
            instance.category_name = obj.category.name
        return instance


class LineItemCreate(BaseModel):
    description: str
    amount: float
    quantity: int = 1
    category_id: Optional[int] = None
    sort_order: int = 0


class LineItemUpdate(BaseModel):
    description: Optional[str] = None
    amount: Optional[float] = None
    quantity: Optional[int] = None
    category_id: Optional[int] = None
    sort_order: Optional[int] = None


# --- Categories ---


class CategoryOut(BaseModel):
    id: int
    name: str
    parent_id: Optional[int]
    is_fixed: bool
    category_type: str
    children: list["CategoryOut"] = []

    model_config = {"from_attributes": True}


class CategoryCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None
    category_type: str = "expense"
    is_fixed: bool = False


# --- Dashboard ---


class DashboardSummary(BaseModel):
    total_income: float
    total_expenses: float
    net: float
    transaction_count: int
    receipts_attached: int


class CategorySpending(BaseModel):
    category: str
    category_id: Optional[int] = None
    total: float
    count: int
    has_children: bool = False


class SubcategorySpending(BaseModel):
    category: str
    total: float
    count: int


class SpendingLineItem(BaseModel):
    line_item_id: int
    description: str
    amount: float
    quantity: int
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    is_remaining: bool
    transaction_id: int
    transaction_date: date
    transaction_merchant: Optional[str]
    transaction_amount: float


class BreadcrumbItem(BaseModel):
    id: int
    name: str


class CategoryDetail(BaseModel):
    category_id: int
    category_name: str
    breadcrumb: list[BreadcrumbItem]
    total: float
    line_items: list[SpendingLineItem]


class MonthlyTrend(BaseModel):
    month: str
    income: float
    expenses: float
    net: float


# --- Category Mappings ---


class CategoryMappingOut(BaseModel):
    id: int
    bank_category: str
    category_id: int
    category_name: str

    model_config = {"from_attributes": True}


class CategoryMappingCreate(BaseModel):
    bank_category: str
    category_id: int


# --- Budget ---


class BudgetLineOut(BaseModel):
    id: int
    category_id: int
    category_name: str
    category_type: str
    is_fixed: bool
    amount: float
    is_overridden: bool = False
    template_amount: float = 0.0

    model_config = {"from_attributes": True}


class BudgetLineCreate(BaseModel):
    category_id: int
    amount: float


class BudgetSummary(BaseModel):
    id: int
    start_date: date
    end_date: date
    line_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BudgetOut(BaseModel):
    id: int
    start_date: date
    end_date: date
    lines: list[BudgetLineOut] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BudgetCreate(BaseModel):
    start_date: date
    end_date: date
    lines: list[BudgetLineCreate] = []


class BudgetUpdate(BaseModel):
    lines: list[BudgetLineCreate] = []


class BudgetPatch(BaseModel):
    start_date: date | None = None
    end_date: date | None = None


# --- Budget Template ---


class BudgetTemplateLineOut(BaseModel):
    id: int
    category_id: int
    category_name: str
    category_type: str
    is_fixed: bool
    amount: float

    model_config = {"from_attributes": True}


class BudgetTemplateOut(BaseModel):
    lines: list[BudgetTemplateLineOut]
    total_income: float
    total_fixed_expenses: float
    discretionary: float
    total_flexible_expenses: float
    unallocated: float


class BudgetTemplateLineCreate(BaseModel):
    category_id: int
    amount: float


# --- Budget vs Actual ---


class BudgetVsActualLine(BaseModel):
    category_id: int
    category_name: str
    category_type: str
    is_fixed: bool
    budgeted: float
    actual: float
    difference: float
    percentage: float


class BudgetVsActualSummary(BaseModel):
    budget_id: int
    start_date: date
    end_date: date
    total_budgeted_income: float
    total_actual_income: float
    total_budgeted_expenses: float
    total_actual_expenses: float
    budgeted_net: float
    actual_net: float
    savings_rate: float
    income_lines: list[BudgetVsActualLine]
    expense_lines: list[BudgetVsActualLine]
    unmapped_expenses: float
    unmapped_income: float
